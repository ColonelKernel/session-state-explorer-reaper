"""Guide-grounded knowledge about REAPER's stock FX and mixing workflows.

This module is *data*, not logic: a small, dependency-free catalogue of the
Cockos stock processors and canonical REAPER workflows, distilled from the two
official references:

* *Up and Running: A REAPER User Guide* v7.75 ("User Guide")
* *The REAPER Cockos Effects Summary Guide* v3.04 ("ReaEffects Guide")

Every entry carries page citations so that recommendations built on top of it
are literature-traceable: an explainable suggestion should be able to say not
just *what* to try but *where the advice comes from*. Third-party plug-ins are
deliberately absent — :func:`lookup_stock_fx` returns ``None`` for them and
callers fall back to keyword heuristics.

Like :mod:`.utils`, this module must stay import-light (stdlib only) so the
parser and tests never pay for audio or UI dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Citation:
    """A pointer into one of the two official guides."""

    doc: str  # "User Guide" | "ReaEffects Guide"
    pages: str  # e.g. "43-44" or "§2.14, pp. 43-44"

    def __str__(self) -> str:  # used verbatim in Recommendation.references
        return f"REAPER {self.doc}, {self.pages}"


@dataclass(frozen=True)
class StockFx:
    """One stock processor: what it is, when to reach for it, and where that
    advice comes from."""

    canonical_name: str
    kind: str  # "stock-plugin" | "js-plugin"
    # Lowercase substrings tested against the normalised FxState.name.
    match_patterns: Tuple[str, ...]
    family: str  # authoritative family for classify_fx_family
    purpose: str
    usage_tips: Tuple[str, ...] = ()
    presets: Tuple[str, ...] = ()
    citations: Tuple[Citation, ...] = ()


@dataclass(frozen=True)
class Workflow:
    """A named, guide-documented REAPER workflow recipe."""

    key: str
    title: str
    recipe: str
    citations: Tuple[Citation, ...] = ()


# ---------------------------------------------------------------------------
# Stock processor catalogue
# ---------------------------------------------------------------------------
# ORDER MATTERS: lookup returns the first entry whose pattern matches, and some
# names nest ("reaverbate" contains "reaverb"), so the more specific entry must
# come first. A regression test pins this.

STOCK_FX: Tuple[StockFx, ...] = (
    StockFx(
        canonical_name="ReaEQ",
        kind="stock-plugin",
        match_patterns=("reaeq",),
        family="EQ",
        purpose=(
            "Cockos parametric equalizer (4 bands by default): fix deficiencies "
            "(excess bass/top, hum, rumble) or enhance presence and warmth."
        ),
        usage_tips=(
            "Use it gently, especially at first — the guide's explicit caveat is "
            "that over-aggressive EQ makes tracks sound worse.",
            "The Action List includes 'Track: Insert ReaEQ (track EQ)' to insert "
            "an instance on any track.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 17-18"),),
    ),
    StockFx(
        canonical_name="ReaComp",
        kind="stock-plugin",
        match_patterns=("reacomp",),
        family="Dynamics",
        purpose=(
            "Cockos stock compressor: smooths volume variation between louder "
            "and quieter passages of a track or folder."
        ),
        usage_tips=(
            "For a vocal ballad the guide suggests a longer attack and release "
            "with a softer knee; percussive material takes a short attack and a "
            "harder knee.",
            "Set the Detector Highpass around 80 Hz so plosives do not trigger "
            "compression, and the Detector Lowpass around 6 kHz so sibilance "
            "does not.",
            "Set the Detector input to Auxiliary Inputs for sidechain/ducking "
            "driven by another track.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 9-10"),),
    ),
    StockFx(
        canonical_name="ReaXcomp",
        kind="stock-plugin",
        match_patterns=("reaxcomp",),
        family="Dynamics",
        purpose=(
            "Multiband compressor: ReaComp-style controls applied per frequency "
            "band; the guide's example shows it on the master track."
        ),
        usage_tips=(
            "Each band has its own Threshold/Ratio; band edges are draggable on "
            "the graph via the vertical divider lines.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 44-45"),),
    ),
    StockFx(
        canonical_name="ReaLimit",
        kind="stock-plugin",
        match_patterns=("realimit",),
        family="Dynamics",
        purpose=(
            "Brickwall limiter for raising overall level under a guaranteed "
            "ceiling, with real-time visual feedback of where limiting occurs."
        ),
        usage_tips=(
            "Threshold sets where limiting begins; Brickwall Ceiling is the "
            "absolute maximum (guide example: -0.75 dB); enable True Peak so the "
            "display uses oversampled true-peak values.",
        ),
        citations=(Citation("ReaEffects Guide", "p. 46"),),
    ),
    StockFx(
        canonical_name="ReaGate",
        kind="stock-plugin",
        match_patterns=("reagate",),
        family="Dynamics",
        purpose=(
            "Noise gate: mutes signal below a threshold (e.g. breaths between "
            "vocal phrases); supports sidechain control and ducking."
        ),
        usage_tips=(
            "Pre-open gives look-ahead so the attack starts before the level "
            "crosses the threshold; varying Hold with a reverb creates gated "
            "reverb.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 24-25"),),
    ),
    StockFx(
        canonical_name="ReaFir",
        kind="stock-plugin",
        match_patterns=("reafir",),
        family="EQ",
        purpose=(
            "FFT EQ + dynamics processor with five modes (EQ, Gate, Compressor, "
            "Convolve L/R, Subtract); one mode per instance."
        ),
        usage_tips=(
            "Compressor mode sets a per-frequency threshold curve — effectively "
            "a many-band compressor, usable as a de-esser by compressing only "
            "the sibilant frequencies.",
            "Subtract mode is the guide's noise-reduction tool: build a noise "
            "profile while playing a noise-only section, then the profiled noise "
            "is subtracted during playback.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 19-23"),),
    ),
    StockFx(
        canonical_name="ReaDelay",
        kind="stock-plugin",
        match_patterns=("readelay",),
        family="Ambience",
        purpose=(
            "Multi-tap delay: a few milliseconds of thickening, slapback, or "
            "ping-pong echo effects."
        ),
        usage_tips=(
            "Delays under ~7 ms are not heard as discrete echoes — use sub-7 ms "
            "settings to fatten a thin track.",
            "Per-tap lowpass/highpass filters restrict which frequencies are "
            "delayed.",
        ),
        presets=(
            "stock - vocal slapback",
            "stock - slap fb",
            "stock - basic 5tap ping p(ong)",
            "stock - vocal fattener",
        ),
        citations=(
            Citation("ReaEffects Guide", "pp. 14-16"),
            Citation("User Guide", "p. 40 (supplied FX presets)"),
        ),
    ),
    # ReaVerbate must precede ReaVerb: "reaverb" is a substring of "reaverbate".
    StockFx(
        canonical_name="ReaVerbate",
        kind="stock-plugin",
        match_patterns=("reaverbate",),
        family="Ambience",
        purpose=(
            "The simpler of the two Cockos reverbs: adds a natural room/hall "
            "feel to tracks recorded dry."
        ),
        usage_tips=(
            "Audible starting point from the guide's examples: room size ~80, "
            "initial delay ~60.",
            "Use the highpass to keep reverb off bass frequencies and the "
            "lowpass to bound its top end.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 32-33"),),
    ),
    StockFx(
        canonical_name="ReaVerb",
        kind="stock-plugin",
        match_patterns=("reaverb",),
        family="Ambience",
        purpose=(
            "Convolution-capable modular reverb built by chaining modules "
            "(impulse File, Reverb/Echo Generator, Filter, Normalize...)."
        ),
        usage_tips=(
            "More modules is not better — a single Reverb Generator or one "
            "convolution impulse File is often sufficient.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 35-41"),),
    ),
    StockFx(
        canonical_name="ReaPitch",
        kind="stock-plugin",
        match_patterns=("reapitch",),
        family="Pitch",
        purpose=(
            "Pitch/formant shifter for harmony effects or thickening; multiple "
            "shifters can run in one instance."
        ),
        usage_tips=(
            "Pairs well with plug-in pin connectors: route the wet signal to a "
            "separate track to pan harmonies independently.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 27-28"),),
    ),
    StockFx(
        canonical_name="ReaTune",
        kind="stock-plugin",
        match_patterns=("reatune",),
        family="Pitch",
        purpose=(
            "Tuner and pitch corrector: tuning mode, automatic correction "
            "(pick key and scale), and manual correction."
        ),
        usage_tips=(
            "For live-instrument tuning insert it in the track's input FX chain; "
            "for correction insert it in the track or item FX chain.",
        ),
        citations=(Citation("ReaEffects Guide", "pp. 29-31"),),
    ),
    StockFx(
        canonical_name="ReaInsert",
        kind="stock-plugin",
        match_patterns=("reainsert",),
        family="Routing",
        purpose=(
            "Hardware insert: patches an external effects unit into the FX "
            "chain via sound-card I/O, with ping-measured latency compensation."
        ),
        citations=(Citation("ReaEffects Guide", "p. 26"),),
    ),
    StockFx(
        canonical_name="JS Loudness Meter",
        kind="js-plugin",
        match_patterns=("loudness_meter", "loudness meter"),
        family="Metering",
        purpose=(
            "Stock analysis plug-in (analysis/loudness_meter) showing Peak, "
            "True Peak, RMS, LUFS (momentary/short-term/integrated) and LRA."
        ),
        usage_tips=(
            "The guide notes LUFS is now generally regarded as the preferred "
            "industry loudness standard; a large Peak-vs-RMS gap simply means "
            "high dynamics.",
            "True Peak estimates the oversampled level after resampling and is "
            "generally higher than the sample peak.",
        ),
        citations=(
            Citation("ReaEffects Guide", "pp. 47-48"),
            Citation("User Guide", "§6.18, p. 120"),
        ),
    ),
    StockFx(
        canonical_name="JS Gain Reduction Scope",
        kind="js-plugin",
        match_patterns=("gain reduction scope", "gain_reduction"),
        family="Metering",
        purpose=(
            "Displays dry and processed signal side by side to audit what an FX "
            "chain does to dynamics."
        ),
        citations=(Citation("ReaEffects Guide", "pp. 52-53"),),
    ),
    StockFx(
        canonical_name="JS Frequency Spectrum Analyzer",
        kind="js-plugin",
        match_patterns=("gfxanalyzer", "frequency spectrum analyzer"),
        family="Metering",
        purpose="Frequency-domain analyzer (analysis/gfxanalyzer).",
        citations=(Citation("ReaEffects Guide", "pp. 58-59"),),
    ),
    StockFx(
        canonical_name="JS Oscilloscope Meter",
        kind="js-plugin",
        match_patterns=("gfxscope", "oscilloscope"),
        family="Metering",
        purpose="Time-domain waveform display (analysis/gfxscope).",
        citations=(Citation("ReaEffects Guide", "p. 60"),),
    ),
    StockFx(
        canonical_name="JS Spectrograph Meter",
        kind="js-plugin",
        match_patterns=("gfxspectrograph", "spectrograph"),
        family="Metering",
        purpose=(
            "Spectrogram display (analysis/gfxspectrograph); higher FFT sizes "
            "resolve low-frequency problems (plosives, handling noise), lower "
            "sizes resolve transients."
        ),
        citations=(Citation("ReaEffects Guide", "p. 62"),),
    ),
    StockFx(
        canonical_name="JS Channel Mapper-Downmixer",
        kind="js-plugin",
        match_patterns=("channel_mapper", "channel mapper"),
        family="Routing",
        purpose=(
            "Mixes multi-channel streams within a track back to chosen outputs "
            "— the key to blending parallel FX streams created with plug-in pin "
            "connectors."
        ),
        citations=(Citation("ReaEffects Guide", "pp. 33-34"),),
    ),
)


# ---------------------------------------------------------------------------
# Workflow recipes
# ---------------------------------------------------------------------------

WORKFLOWS: Dict[str, Workflow] = {
    w.key: w
    for w in (
        Workflow(
            key="fx_bus",
            title="Shared FX bus (send/return)",
            recipe=(
                "Insert a new track (Ctrl+T) and name it, e.g. 'FX Bus'; put one "
                "shared effect on it; then select the source tracks, right-click "
                "one track's ROUTE button and choose Sends > [FX Bus]. Each track "
                "keeps its dry path to the master while a copy feeds the bus. If "
                "the effect is too strong there are four levers, in order of "
                "least disruption: the plug-in's wet/dry control, the receive "
                "levels, per-track send levels, or the bus fader. Sends default "
                "to Post-Fader (Post-Pan)."
            ),
            citations=(Citation("User Guide", "§2.14, pp. 43-44"),),
        ),
        Workflow(
            key="folder_submix",
            title="Folder-track submix",
            recipe=(
                "Insert a track above the related tracks (Ctrl+T), click its "
                "folder icon once, and click the last member's icon twice — or "
                "select the tracks and right-click > 'Move tracks to folder'. "
                "Children route to the folder automatically, so folder volume "
                "and FX act on the whole submix: set child faders relative to "
                "each other, then the folder fader for the group's level. Do not "
                "manually disable master/parent send on children inside a "
                "folder, or their output will no longer reach it."
            ),
            citations=(Citation("User Guide", "§5.12-5.13, pp. 98-101"),),
        ),
        Workflow(
            key="vca_group",
            title="VCA grouping",
            recipe=(
                "Use the Track Grouping Matrix (Ctrl+Alt+G) with VCA lead/follow "
                "cells when you only want linked fader control: a VCA control "
                "track is not a submix and passes no audio, so audio FX on it "
                "make no sense."
            ),
            citations=(Citation("User Guide", "§5.16, pp. 107-108"),),
        ),
        Workflow(
            key="sidechain_send",
            title="Sidechain via channels 3/4",
            recipe=(
                "Create a send from channels 1/2 of the control track to "
                "channels 3/4 of the destination track, then set the detector "
                "input of ReaComp or ReaGate on the destination to Auxiliary "
                "Inputs: the threshold now responds to the control track while "
                "processing is applied to the destination."
            ),
            citations=(Citation("ReaEffects Guide", "p. 11"),),
        ),
        Workflow(
            key="parallel_fx",
            title="Parallel FX chains",
            recipe=(
                "If two processors are alternatives rather than a series, "
                "right-click the second and choose 'Run selected FX in parallel "
                "with previous FX' to make the topology explicit. For a "
                "meterable wet/dry split, route a plug-in's output to channels "
                "3/4 via its pin connector and blend with the JS Channel "
                "Mapper-Downmixer."
            ),
            citations=(
                Citation("User Guide", "§6.8, p. 116"),
                Citation("ReaEffects Guide", "pp. 33-34"),
            ),
        ),
        Workflow(
            key="freeze",
            title="Freezing settled processing",
            recipe=(
                "The FX-chain right-click menu offers 'Freeze track to stereo, "
                "up to last selected FX': settled processors are rendered into "
                "the item while the rest stay live; unfreeze restores "
                "everything. Offline FX are deliberately excluded from a freeze."
            ),
            citations=(Citation("User Guide", "§6.17, pp. 119-120"),),
        ),
        Workflow(
            key="offline_vs_bypass",
            title="Offline vs bypass",
            recipe=(
                "Bypassed FX (Ctrl+B) still consume some CPU; offline FX "
                "(Ctrl+Alt+B) consume none and are fully inactive — offline is "
                "the honest state for 'parked' processors. The Performance "
                "Meter (Ctrl+Alt+P) shows whether it matters; double-click a "
                "track name there to jump to the culprit FX chain."
            ),
            citations=(Citation("User Guide", "§2.12/§2.16, pp. 40-42, 45"),),
        ),
        Workflow(
            key="monitoring_fx",
            title="Monitoring FX chain",
            recipe=(
                "The canonical home for listen-only analyzers is the Monitoring "
                "FX chain (View > Monitoring FX, or Shift+click the master "
                "track's FX button): FX there apply per hardware output for "
                "listening only — never rendered and not stored in the project "
                "file."
            ),
            citations=(Citation("User Guide", "§6.13, p. 118"),),
        ),
        Workflow(
            key="recovery_mode",
            title="Recovery mode (FX offline)",
            recipe=(
                "Opening a project with 'Open with FX offline (recovery mode)' "
                "sets every FX offline to isolate a crashing plug-in; bring FX "
                "back online one at a time (Ctrl+Alt+B) until the culprit "
                "surfaces, then replace it."
            ),
            citations=(Citation("User Guide", "§6.16, p. 119"),),
        ),
        Workflow(
            key="routing_matrix_audit",
            title="Routing Matrix audit",
            recipe=(
                "The Routing Matrix (Alt+R) shows every send/receive as a grid "
                "cell; right-click a cell for its level/pan/mute controls or to "
                "delete it. 'Show sends in TCP' (Options) keeps parked sends "
                "visible so they are not forgotten."
            ),
            citations=(Citation("User Guide", "§2.22-2.23, pp. 48-49"),),
        ),
        Workflow(
            key="default_fx_chain",
            title="Default channel strip for new tracks",
            recipe=(
                "Add ReaEQ and ReaComp to a track's FX chain, untick both to "
                "bypass, then right-click an FX and choose 'FX Chain, Save all "
                "FX as default for new tracks': every new track then carries "
                "EQ + dynamics ready on demand, costing no CPU until enabled "
                "because they were saved bypassed."
            ),
            citations=(Citation("User Guide", "§2.12 Tip 3, p. 42"),),
        ),
    )
}


# Ordered stock candidates per family, for building concrete suggestions.
FAMILY_STOCK_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "EQ": ("ReaEQ", "ReaFir"),
    "Dynamics": ("ReaComp", "ReaXcomp", "ReaGate", "ReaLimit"),
    "Ambience": ("ReaVerbate", "ReaVerb", "ReaDelay"),
    "Pitch": ("ReaTune", "ReaPitch"),
    "Metering": ("JS Loudness Meter",),
}


# ---------------------------------------------------------------------------
# Lookup API
# ---------------------------------------------------------------------------

_TYPE_PREFIXES = (
    "vst3:", "vst:", "js:", "au:", "aufx:", "clap:", "lv2:", "dx:",
)


def _normalize_fx_name(name: str) -> str:
    """Lowercase an FxState.name and strip type prefix and vendor suffix."""

    lowered = name.strip().lower()
    for prefix in _TYPE_PREFIXES:
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix):].strip()
            break
    # Drop a trailing vendor parenthetical, e.g. "reacomp (cockos)".
    if lowered.endswith(")") and "(" in lowered:
        lowered = lowered[: lowered.rfind("(")].strip()
    return lowered


def lookup_stock_fx(name: Optional[str]) -> Optional[StockFx]:
    """Return the :class:`StockFx` entry matching a parsed FX name.

    Returns ``None`` for third-party or unrecognisable names, so callers can
    fall back to keyword heuristics. First match in ``STOCK_FX`` order wins.
    """

    if not name:
        return None
    normalized = _normalize_fx_name(name)
    if not normalized:
        return None
    for entry in STOCK_FX:
        if any(pattern in normalized for pattern in entry.match_patterns):
            return entry
    return None


def workflow(key: str) -> Workflow:
    """Fetch a workflow recipe by key (raises KeyError on unknown keys)."""

    return WORKFLOWS[key]
