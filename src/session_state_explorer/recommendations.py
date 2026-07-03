"""Rule-based, explainable recommendations derived from the DAW-state graph.

These are deliberately simple *heuristics*, not an AI mixer. Their purpose is to
demonstrate how an interpretable graph representation can support explainable,
graph-level suggestions while preserving producer agency: every recommendation
carries an explanation, a suggested action, related node ids for traceability, and
an explicit caveat.

Implemented rules:

1. Missing shared reverb/delay send (individual ambience FX, no shared return).
2. Vocal track without a basic vocal chain.
3. Dense FX chain warning (> 6 processors on one track).
4. Missing bus structure (> 8 tracks but no routes/sends detected).
5. Descriptor-based level imbalance (one stem much hotter than the rest).
"""

from __future__ import annotations

from statistics import median
from typing import List, Optional

import networkx as nx

from .models import AudioDescriptorSet, ProjectState, Recommendation, TrackState
from .utils import is_ambience_fx, is_vocal_name

_CAVEAT = "This is a graph-based heuristic, not an objective mixing rule."

# Tunable thresholds (kept here so they are easy to find and justify).
DENSE_FX_THRESHOLD = 6
MANY_TRACKS_THRESHOLD = 8
AMBIENCE_TRACK_MIN = 2
LEVEL_IMBALANCE_RATIO = 2.0


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
                "Create a reverb/delay return track and route the relevant tracks to it "
                "with sends, rather than instantiating ambience separately per track."
            ),
            caveat=_CAVEAT,
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
                ("EQ", "EQ"),
                ("compression", "Dynamics"),
                ("de-essing", "Dynamics"),
                ("ambience send", "Ambience"),
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
                    "Review the vocal chain; candidate additions include: "
                    + ", ".join(missing)
                    + "."
                ),
                caveat=_CAVEAT + " Vocal processing is highly stylistic and optional.",
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
                    "Consider labelling the track's processing intent, separating "
                    "corrective from creative processing, or routing to a bus so the "
                    "chain is easier to document and revise."
                ),
                caveat=_CAVEAT,
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
                "Create group/bus tracks for related instruments and route them there "
                "to centralise level and processing decisions."
            ),
            caveat=_CAVEAT,
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
                "Compare these items' levels against the rest of the session and "
                "adjust gain staging if the imbalance is unintended."
            ),
            caveat=_CAVEAT + " Level differences are often intentional.",
        )
    ]


def _basename(path: str) -> str:
    from os.path import basename

    return basename(str(path).replace("\\", "/")) or str(path)
