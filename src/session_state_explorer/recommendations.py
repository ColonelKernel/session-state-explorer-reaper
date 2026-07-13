"""Rule-based, explainable recommendations derived from the DAW-state graph.

These are deliberately simple *heuristics*, not an AI mixer. Their purpose is to
demonstrate how an interpretable graph representation can support explainable,
graph-level suggestions while preserving producer agency: every recommendation
carries an explanation, a suggested action, related node ids for traceability,
an explicit caveat, and — where the advice is REAPER-specific — page citations
into the official guides (see :mod:`.reaper_fx_knowledge`).

Implemented rules:

1.  Missing shared reverb/delay send (individual ambience FX, no shared return).
2.  Vocal track without a basic vocal chain.
3.  Dense FX chain warning (> 6 processors on one track).
4.  Missing bus structure (> 8 tracks but no routes/sends detected).
5.  Descriptor-based level imbalance (stems much hotter than the rest).
6.  Every FX offline (recovery-mode fingerprint).
7.  Muted or near-silent sends (routing debris).
8.  Bypassed-but-online FX accumulating on a track.
9.  Manual submix where the guide prefers a folder track.
10. Clipping-risk stems (peak at or near digital full scale).
11. Analysis/metering FX in the render path (Monitoring FX candidate).
"""

from __future__ import annotations

from statistics import median
from typing import List, Optional

import networkx as nx

from .models import AudioDescriptorSet, ProjectState, Recommendation, TrackState
from .reaper_fx_knowledge import STOCK_FX, WORKFLOWS, lookup_stock_fx
from .utils import is_ambience_fx, is_vocal_name

_CAVEAT = "This is a graph-based heuristic, not an objective mixing rule."

# Tunable thresholds (kept here so they are easy to find and justify).
DENSE_FX_THRESHOLD = 6
MANY_TRACKS_THRESHOLD = 8
AMBIENCE_TRACK_MIN = 2
LEVEL_IMBALANCE_RATIO = 2.0
ALL_OFFLINE_MIN_FX = 3  # fewer offline FX than this is not a pattern
BYPASSED_FX_MIN = 2  # per-track bypassed-but-online count worth mentioning
MUTED_SEND_FLOOR_DB = -60.0  # a send below this is effectively silent
CLIPPING_PEAK_THRESHOLD = 0.99  # sample peak considered "at full scale"


def _refs(*keys_and_names: str) -> List[str]:
    """Collect citation strings from workflow keys and stock-FX names."""

    refs: List[str] = []
    stock_by_name = {fx.canonical_name: fx for fx in STOCK_FX}
    for key in keys_and_names:
        source = WORKFLOWS.get(key) or stock_by_name.get(key)
        if source is None:
            continue
        for citation in source.citations:
            text = str(citation)
            if text not in refs:
                refs.append(text)
    return refs


def generate_recommendations(
    project: ProjectState,
    graph: Optional[nx.DiGraph] = None,
    descriptors: Optional[List[AudioDescriptorSet]] = None,
) -> List[Recommendation]:
    """Run every rule and return the recommendations that apply."""

    descriptors = descriptors or []
    recs: List[Recommendation] = []

    recs.extend(_rule_shared_ambience_bus(project))
    recs.extend(_rule_vocal_chain(project))
    recs.extend(_rule_dense_fx(project))
    recs.extend(_rule_missing_bus(project))
    recs.extend(_rule_level_imbalance(descriptors))
    recs.extend(_rule_all_fx_offline(project))
    recs.extend(_rule_muted_sends(project))
    recs.extend(_rule_bypassed_fx(project))
    recs.extend(_rule_manual_submix(project))
    recs.extend(_rule_clipping_risk(descriptors))
    recs.extend(_rule_meters_in_render_path(project))

    return recs


# ---------------------------------------------------------------------------
# Rule 1: shared ambience bus
# ---------------------------------------------------------------------------

def _rule_shared_ambience_bus(project: ProjectState) -> List[Recommendation]:
    ambience_tracks = [
        t for t in project.tracks
        if (t.role or "") != "Bus" and any(is_ambience_fx(f.name) for f in t.fx)
    ]
    if len(ambience_tracks) < AMBIENCE_TRACK_MIN:
        return []

    if _has_shared_ambience_return(project):
        return []

    related = [t.id for t in ambience_tracks]
    names = ", ".join(t.name or t.id for t in ambience_tracks)
    return [
        Recommendation(
            id="rec-ambience-bus",
            title="Consider creating a shared ambience bus",
            severity="suggestion",
            confidence=0.6,
            related_node_ids=related,
            explanation=(
                f"Several tracks use ambience-like FX individually ({names}), but the "
                "graph does not show a shared send/return for reverb or delay. A shared "
                "ambience bus could improve mix cohesion and make the session easier to "
                "control from one place."
            ),
            suggested_action=(
                "One REAPER-native candidate is the FX Bus recipe: insert a new "
                "track named e.g. 'FX Bus' carrying a single shared ambience "
                "effect — ReaVerbate is the simple stock choice (room size ~80, "
                "initial delay ~60 is an audible starting point; use its "
                "highpass to keep reverb off the low end), ReaVerb for "
                "convolution, or ReaDelay starting from a stock preset such as "
                "'stock - vocal slapback'. Select the source tracks, right-click "
                "one track's ROUTE button and choose Sends > [FX Bus]; each "
                "track keeps its dry path while a copy feeds the bus. If the "
                "effect is too strong, the four levers in order of least "
                "disruption are the plug-in wet/dry control, receive levels, "
                "per-track send levels, then the bus fader."
            ),
            caveat=_CAVEAT,
            references=_refs("fx_bus", "ReaVerbate", "ReaVerb", "ReaDelay"),
        )
    ]


def _has_shared_ambience_return(project: ProjectState) -> bool:
    """True if there is a plausible shared ambience return in the session."""

    targeted_track_ids = {r.target_track_id for r in project.routes if r.target_track_id}
    for track in project.tracks:
        track_is_ambience = any(is_ambience_fx(f.name) for f in track.fx)
        looks_like_return = (track.role or "") == "Bus" or is_ambience_fx(track.name)
        receives_sends = track.id in targeted_track_ids
        if track_is_ambience and (looks_like_return or receives_sends):
            return True
    return False


# ---------------------------------------------------------------------------
# Rule 2: vocal chain
# ---------------------------------------------------------------------------

def _rule_vocal_chain(project: ProjectState) -> List[Recommendation]:
    recs: List[Recommendation] = []
    for track in project.tracks:
        if (track.role or "") != "Vocal" and not is_vocal_name(track.name):
            continue
        families = {f.family for f in track.fx}
        canonical_present = families & {"EQ", "Dynamics", "Ambience"}
        # Under-processed if it has fewer than two canonical vocal-chain elements.
        if len(canonical_present) >= 2:
            continue

        missing = [
            label
            for label, fam in (
                ("EQ (ReaEQ — the guide's advice: use it gently)", "EQ"),
                (
                    "compression (ReaComp; for a ballad: longer attack/release, "
                    "soft knee, detector highpass ~80 Hz so plosives don't "
                    "trigger it)",
                    "Dynamics",
                ),
                (
                    "de-essing (ReaFir in Compressor mode, compressing only the "
                    "sibilant frequencies)",
                    "Dynamics",
                ),
                (
                    "an ambience send to a shared bus (ReaVerbate, or ReaDelay's "
                    "'stock - vocal slapback' preset)",
                    "Ambience",
                ),
            )
            if fam not in families
        ]
        recs.append(
            Recommendation(
                id=f"rec-vocal-chain-{track.id}",
                title=f"Vocal track '{track.name or track.id}' appears under-processed",
                severity="suggestion",
                confidence=0.5,
                related_node_ids=[track.id] + [f.id for f in track.fx],
                explanation=(
                    "The track name suggests a vocal role, but its FX chain does not "
                    "show the common vocal-processing elements one might expect "
                    f"(currently present: {sorted(canonical_present) or 'none'}). "
                    "Consider whether EQ, compression, de-essing, and an ambience send "
                    "would serve the part."
                ),
                suggested_action=(
                    "Review the vocal chain; stock candidates for the missing "
                    "elements: "
                    + "; ".join(missing)
                    + ". A zero-cost way to keep the basics ready is the guide's "
                    "default-chain recipe: ReaEQ + ReaComp saved bypassed as the "
                    "default FX chain for new tracks."
                ),
                caveat=_CAVEAT + " Vocal processing is highly stylistic and optional.",
                references=_refs(
                    "ReaEQ", "ReaComp", "ReaFir", "ReaVerbate", "default_fx_chain"
                ),
            )
        )
    return recs


# ---------------------------------------------------------------------------
# Rule 3: dense FX chain
# ---------------------------------------------------------------------------

def _rule_dense_fx(project: ProjectState) -> List[Recommendation]:
    recs: List[Recommendation] = []
    for track in project.tracks:
        if len(track.fx) <= DENSE_FX_THRESHOLD:
            continue
        recs.append(
            Recommendation(
                id=f"rec-dense-fx-{track.id}",
                title=f"Track '{track.name or track.id}' has a dense FX chain",
                severity="info",
                confidence=0.7,
                related_node_ids=[track.id] + [f.id for f in track.fx],
                explanation=(
                    f"This track carries {len(track.fx)} processors. Dense chains can "
                    "reduce interpretability and make later revisions harder to reason "
                    "about."
                ),
                suggested_action=(
                    "REAPER-native ways to make a dense chain easier to reason "
                    "about: audit its cost in the Performance Meter (Ctrl+Alt+P; "
                    "double-click the track name there to jump to the chain); "
                    "park 'just in case' processors offline (Ctrl+Alt+B — "
                    "offline costs no CPU, unlike bypass); freeze the settled "
                    "part via 'Freeze track to stereo, up to last selected FX'; "
                    "and if two processors are alternatives rather than a "
                    "series, 'Run selected FX in parallel with previous FX' "
                    "makes the topology explicit. Saving the chain with a "
                    "descriptive name (FX > Save FX Chain) documents intent."
                ),
                caveat=_CAVEAT,
                references=_refs("offline_vs_bypass", "freeze", "parallel_fx"),
            )
        )
    return recs


# ---------------------------------------------------------------------------
# Rule 4: missing bus structure
# ---------------------------------------------------------------------------

def _rule_missing_bus(project: ProjectState) -> List[Recommendation]:
    if len(project.tracks) <= MANY_TRACKS_THRESHOLD:
        return []
    if project.routes:
        return []
    return [
        Recommendation(
            id="rec-missing-bus",
            title="Consider adding bus/group structure",
            severity="suggestion",
            confidence=0.55,
            related_node_ids=[t.id for t in project.tracks],
            explanation=(
                f"The project has {len(project.tracks)} tracks, but no explicit bus or "
                "send routing was detected in the graph. Grouping related material "
                "(drums, vocals, guitars, synths) can improve mix control and make the "
                "session structure clearer."
            ),
            suggested_action=(
                "REAPER offers three grouping structures. Folder tracks — which "
                "the guide calls 'a smarter and potentially more powerful way of "
                "creating a submix' — are the first candidate: select related "
                "tracks, right-click > 'Move tracks to folder'; children route "
                "to the folder automatically, so folder volume/FX govern the "
                "submix. An FX bus fed by sends fits when tracks should keep "
                "their dry path to the master; VCA grouping (Track Grouping "
                "Matrix, Ctrl+Alt+G) fits when only linked fader control is "
                "wanted. Which structure fits depends on what the groups mean "
                "in this session."
            ),
            caveat=_CAVEAT,
            references=_refs("folder_submix", "fx_bus", "vca_group"),
        )
    ]


# ---------------------------------------------------------------------------
# Rule 5: descriptor-based level imbalance
# ---------------------------------------------------------------------------

def _rule_level_imbalance(
    descriptors: List[AudioDescriptorSet],
) -> List[Recommendation]:
    usable = [
        d
        for d in descriptors
        if d.available and (d.rms_mean is not None or d.peak_amplitude is not None)
    ]
    if len(usable) < 2:
        return []

    peaks = [d.peak_amplitude for d in usable if d.peak_amplitude is not None]
    rmss = [d.rms_mean for d in usable if d.rms_mean is not None]
    median_peak = median(peaks) if peaks else None
    median_rms = median(rmss) if rmss else None

    hot: List[AudioDescriptorSet] = []
    for descriptor in usable:
        hot_peak = (
            median_peak
            and descriptor.peak_amplitude is not None
            and median_peak > 0
            and descriptor.peak_amplitude > LEVEL_IMBALANCE_RATIO * median_peak
        )
        hot_rms = (
            median_rms
            and descriptor.rms_mean is not None
            and median_rms > 0
            and descriptor.rms_mean > LEVEL_IMBALANCE_RATIO * median_rms
        )
        if hot_peak or hot_rms:
            hot.append(descriptor)

    if not hot:
        return []

    # A single aggregated recommendation: on stem-heavy sessions several files
    # routinely exceed the median, and one card per file reads as noise.
    names = [_basename(d.file_path or d.node_id or "an audio item") for d in hot]
    listed = ", ".join(names[:6]) + (f" and {len(names) - 6} more" if len(names) > 6 else "")
    subject = (
        f"One audio item ({listed}) has"
        if len(hot) == 1
        else f"{len(hot)} audio items ({listed}) have"
    )
    return [
        Recommendation(
            id="rec-level-imbalance",
            title="Potential level imbalance detected",
            severity="warning",
            confidence=0.5,
            related_node_ids=[d.node_id for d in hot if d.node_id],
            explanation=(
                f"{subject} a substantially higher RMS or peak level than the "
                "project median. This may be intentional (a feature, a lead "
                "element), but it is worth checking in context."
            ),
            suggested_action=(
                "A concrete way to check inside REAPER: read levels with the "
                "stock JS Loudness Meter — preferring LUFS, which the guide "
                "notes is now generally regarded as the preferred industry "
                "standard (a large peak-vs-RMS gap simply means high dynamics) "
                "— or use the Action List's 'calculate loudness' actions, which "
                "analyse selected tracks/items without touching FX chains. When "
                "re-checking after a gain change, click a track's peak readout "
                "to clear it (Ctrl+click clears all) without stopping playback."
            ),
            caveat=_CAVEAT + " Level differences are often intentional.",
            references=_refs("JS Loudness Meter"),
        )
    ]


# ---------------------------------------------------------------------------
# Rule 6: every FX offline (recovery-mode fingerprint)
# ---------------------------------------------------------------------------

def _rule_all_fx_offline(project: ProjectState) -> List[Recommendation]:
    fx = project.fx
    if len(fx) < ALL_OFFLINE_MIN_FX:
        return []
    if not all(f.offline is True for f in fx):
        return []
    return [
        Recommendation(
            id="rec-fx-all-offline",
            title="Every FX in this session is offline",
            severity="warning",
            confidence=0.7,
            related_node_ids=[f.id for f in fx],
            explanation=(
                f"All {len(fx)} processors are offline (unloaded), which is the "
                "state REAPER produces when a project is opened with 'Open with "
                "FX offline (recovery mode)' — often used to isolate a crashing "
                "plug-in. If it was not intentional, note that this session will "
                "currently render with no processing at all."
            ),
            suggested_action=(
                "If recovery mode was the intent, the guide's workflow is to "
                "bring FX back online one at a time (Ctrl+Alt+B toggles offline) "
                "until the culprit surfaces, then replace it with an equivalent."
            ),
            caveat=_CAVEAT,
            references=_refs("recovery_mode", "offline_vs_bypass"),
        )
    ]


# ---------------------------------------------------------------------------
# Rule 7: muted or near-silent sends
# ---------------------------------------------------------------------------

def _rule_muted_sends(project: ProjectState) -> List[Recommendation]:
    silent = [
        r
        for r in project.routes
        if r.mute is True
        or (r.volume_db is not None and r.volume_db < MUTED_SEND_FLOOR_DB)
    ]
    if not silent:
        return []

    name_of = {t.id: (t.name or t.id) for t in project.tracks}
    labels = [
        f"{name_of.get(r.source_track_id, r.source_name or '?')} -> "
        f"{name_of.get(r.target_track_id, r.target_name or '?')}"
        for r in silent
    ]
    plural = "sends" if len(silent) > 1 else "send"
    return [
        Recommendation(
            id="rec-muted-sends",
            title=f"{len(silent)} muted or near-silent {plural} in the routing graph",
            severity="info",
            confidence=0.6,
            related_node_ids=[r.id for r in silent],
            explanation=(
                f"The following {plural} exist in the graph but carry "
                f"effectively nothing: {'; '.join(labels)}. A muted send is "
                "sometimes a deliberate A/B switch, so this is a hygiene flag, "
                "not an error."
            ),
            suggested_action=(
                "Audit them in the Routing Matrix (Alt+R) — right-click a cell "
                "for its level/pan/mute controls and delete leftovers; if a "
                "send is a parked creative decision, 'Show sends in TCP' "
                "(Options menu) keeps it visible so it isn't forgotten."
            ),
            caveat=_CAVEAT,
            references=_refs("routing_matrix_audit"),
        )
    ]


# ---------------------------------------------------------------------------
# Rule 8: bypassed-but-online FX accumulating
# ---------------------------------------------------------------------------

def _rule_bypassed_fx(project: ProjectState) -> List[Recommendation]:
    affected: List[TrackState] = []
    fx_ids: List[str] = []
    for track in project.tracks:
        parked = [f for f in track.fx if f.enabled is False and f.offline is not True]
        if len(parked) >= BYPASSED_FX_MIN:
            affected.append(track)
            fx_ids.extend(f.id for f in parked)
    if not affected:
        return []

    names = ", ".join(t.name or t.id for t in affected)
    return [
        Recommendation(
            id="rec-bypassed-fx",
            title="Bypassed-but-online FX are accumulating",
            severity="info",
            confidence=0.55,
            related_node_ids=[t.id for t in affected] + fx_ids,
            explanation=(
                f"Tracks with two or more bypassed processors: {names}. The "
                "guide notes bypassed FX still consume some CPU, whereas "
                "offline FX consume none."
            ),
            suggested_action=(
                "Set 'just in case' processors offline (Ctrl+Alt+B) rather than "
                "bypassed; remove abandoned experiments; or, if a chain is "
                "settled, freeze the track (noting that offline FX are "
                "deliberately excluded from a freeze). The Performance Meter "
                "(Ctrl+Alt+P) shows whether any of this matters on this machine."
            ),
            caveat=_CAVEAT,
            references=_refs("offline_vs_bypass", "freeze"),
        )
    ]


# ---------------------------------------------------------------------------
# Rule 9: manual submix where the guide prefers a folder
# ---------------------------------------------------------------------------

def _rule_manual_submix(project: ProjectState) -> List[Recommendation]:
    track_by_id = {t.id: t for t in project.tracks}
    sources_of: dict[str, List[TrackState]] = {}
    for route in project.routes:
        if route.route_type != "send" or not route.source_track_id:
            continue
        if not route.target_track_id:
            continue
        source = track_by_id.get(route.source_track_id)
        if source is not None:
            bucket = sources_of.setdefault(route.target_track_id, [])
            # A single track may feed one bus via several sends (e.g. parallel sends on
            # different channels); count each distinct source once so two sends from one
            # track never look like a multi-track submix.
            if all(existing.id != source.id for existing in bucket):
                bucket.append(source)

    submixes = []
    for target_id, sources in sources_of.items():
        # The other-DAW submix pattern: >= 2 sources, each with its direct
        # master/parent send explicitly disabled (False, not merely unknown).
        if len(sources) >= 2 and all(s.main_send is False for s in sources):
            submixes.append((target_id, sources))
    if not submixes:
        return []

    name_of = {t.id: (t.name or t.id) for t in project.tracks}
    descriptions = [
        f"{', '.join(name_of.get(s.id, s.id) for s in sources)} -> "
        f"{name_of.get(target_id, target_id)}"
        for target_id, sources in submixes
    ]
    related = []
    for target_id, sources in submixes:
        related.append(target_id)
        related.extend(s.id for s in sources)
    return [
        Recommendation(
            id="rec-manual-submix",
            title="Manual submix detected — a folder track is the guide-preferred structure",
            severity="suggestion",
            confidence=0.6,
            related_node_ids=related,
            explanation=(
                "These tracks have their master/parent send disabled and "
                "converge on one bus via sends — the traditional submix "
                f"pattern: {'; '.join(descriptions)}. The guide explicitly "
                "calls the folder method 'a smarter and potentially more "
                "powerful way of creating a submix'."
            ),
            suggested_action=(
                "Select the member tracks and right-click > 'Move tracks to "
                "folder' (or Ctrl+T plus the folder icon); the folder receives "
                "them automatically with no send bookkeeping, and folder "
                "volume/FX then govern the submix. If converting, do NOT "
                "manually disable master/parent send on children inside a "
                "folder, or their output will no longer reach it."
            ),
            caveat=(
                _CAVEAT + " The existing send-based structure is perfectly "
                "valid — this is an alternative, not a correction."
            ),
            references=_refs("folder_submix"),
        )
    ]


# ---------------------------------------------------------------------------
# Rule 10: clipping-risk stems
# ---------------------------------------------------------------------------

def _rule_clipping_risk(
    descriptors: List[AudioDescriptorSet],
) -> List[Recommendation]:
    hot = [
        d
        for d in descriptors
        if d.available
        and d.peak_amplitude is not None
        and d.peak_amplitude >= CLIPPING_PEAK_THRESHOLD
    ]
    if not hot:
        return []

    names = ", ".join(_basename(d.file_path or d.node_id or "?") for d in hot)
    plural = "files peak" if len(hot) > 1 else "file peaks"
    return [
        Recommendation(
            id="rec-clipping-risk",
            title="Source audio at or near digital full scale",
            severity="warning",
            confidence=0.6,
            related_node_ids=[d.node_id for d in hot if d.node_id],
            explanation=(
                f"{len(hot)} source {plural} at or near full scale ({names}), "
                "which leaves no headroom and risks true-peak overs after "
                "resampling — the guide notes True Peak (the oversampled level) "
                "is generally higher than the sample peak."
            ),
            suggested_action=(
                "Pull item/track gain down at the source rather than at the "
                "master; verify with the JS Loudness Meter with True Peak "
                "display enabled; and if a ceiling is genuinely needed, "
                "ReaLimit is the stock brickwall option (Threshold sets where "
                "limiting begins, Brickwall Ceiling the absolute maximum — the "
                "guide's example uses -0.75 dB)."
            ),
            caveat=(
                _CAVEAT + " Hot stems that never sum near full scale in "
                "context may be fine as-is."
            ),
            references=_refs("ReaLimit", "JS Loudness Meter"),
        )
    ]


# ---------------------------------------------------------------------------
# Rule 11: metering FX in the render path
# ---------------------------------------------------------------------------

def _rule_meters_in_render_path(project: ProjectState) -> List[Recommendation]:
    meters = []
    for track in project.tracks:
        for f in track.fx:
            if f.chain == "main" and (f.family == "Metering" or _is_stock_meter(f.name)):
                meters.append((track, f))
    if not meters:
        return []

    labels = ", ".join(
        f"{f.name} (on {t.name or t.id})" for t, f in meters
    )
    return [
        Recommendation(
            id="rec-meters-in-render-path",
            title="Analysis/metering FX sit in the render path",
            severity="info",
            confidence=0.5,
            related_node_ids=[f.id for _, f in meters],
            explanation=(
                f"Analysis-only plug-ins found in ordinary FX chains: {labels}. "
                "That works, but the guide's canonical home for listen-only "
                "analyzers is the Monitoring FX chain, which never appears in "
                "renders."
            ),
            suggested_action=(
                "Consider moving pure meters to the Monitoring FX chain (View > "
                "Monitoring FX, or Shift+click the master track's FX button). "
                "The trade-off is that Monitoring FX are not stored in the "
                "project file — keep a meter in-chain if it should be saved "
                "with the session."
            ),
            caveat=_CAVEAT,
            references=_refs("monitoring_fx"),
        )
    ]


def _is_stock_meter(name: Optional[str]) -> bool:
    stock = lookup_stock_fx(name)
    return stock is not None and stock.family == "Metering"


def _basename(path: str) -> str:
    from os.path import basename

    return basename(str(path).replace("\\", "/")) or str(path)
