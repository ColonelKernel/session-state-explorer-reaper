"""Typed data models for the parsed DAW-state.

These ``pydantic`` v2 models describe what the prototype can confidently extract
from a REAPER ``.rpp`` file. The design favours *transparency about uncertainty*
over completeness: optional fields default to ``None`` and raw source lines are
preserved (``raw_line`` / ``raw_lines``) so the UI can show traceability between a
parsed value and the underlying project text.

Nothing here attempts to reconstruct plug-in-private state. The models capture the
accessible, human-meaningful surface of a session.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["info", "suggestion", "warning"]


class FxState(BaseModel):
    """A single processor in a track's FX chain, as observed in the ``.rpp``."""

    id: str
    track_id: str
    index: int
    name: str
    fx_type: Optional[str] = None  # e.g. "VST", "VST3", "JS", "AU", "CLAP"
    family: Optional[str] = None  # heuristic family: EQ / Dynamics / Ambience / ...
    enabled: Optional[bool] = None  # False when the processor is bypassed
    # True when the plug-in is unloaded/offline; independent of ``enabled``
    # (SDK: TrackFX_GetOffline / TrackFX_SetOffline).
    offline: Optional[bool] = None
    # "main" for the regular FX chain, "rec" for record-input/monitoring FX
    # (an <FXCHAIN_REC> block; monitoring FX on the master track).
    chain: str = "main"
    preset: Optional[str] = None
    raw_line: Optional[str] = None


class MediaItemState(BaseModel):
    """A media item (clip) placed on a track."""

    id: str
    track_id: str
    name: Optional[str] = None
    position: Optional[float] = None  # seconds
    length: Optional[float] = None  # seconds
    source_file: Optional[str] = None
    source_type: Optional[str] = None  # e.g. "WAVE", "MP3", "FLAC", "MIDI"
    raw_lines: List[str] = Field(default_factory=list)


class RouteState(BaseModel):
    """A send / receive / routing relationship between tracks.

    REAPER stores sends as ``AUXRECV`` lines on the *receiving* track that point at
    the *source* track by index. We normalise this into a directed source -> target
    relationship. When the source cannot be resolved confidently, ``route_type`` is
    set to ``"unresolved"``, ``source_track_id`` is ``None`` (the receiving track is
    still a real, known target) and a warning is recorded on the project.
    """

    id: str
    source_track_id: Optional[str] = None
    source_name: Optional[str] = None  # description of an unresolved source
    target_track_id: Optional[str] = None
    target_name: Optional[str] = None
    route_type: str = "send"  # "send" | "receive" | "unresolved"
    # Per-send parameters (SDK GetSetTrackSendInfo semantics; token positions in
    # the AUXRECV line are format knowledge, parsed tolerantly).
    send_mode: Optional[int] = None  # 0=post-fader, 1=pre-fx, 2=post-fx (deprecated), 3=post-fx
    volume: Optional[float] = None  # linear send gain, 1.0 = +0dB (SDK D_VOL)
    volume_db: Optional[float] = None  # convenience conversion of ``volume``
    pan: Optional[float] = None  # -1..+1 (SDK D_PAN)
    mute: Optional[bool] = None  # send mute (SDK B_MUTE)
    raw_line: Optional[str] = None


class TrackState(BaseModel):
    """A single track and its observable state."""

    id: str
    index: int
    name: Optional[str] = None
    role: Optional[str] = None  # heuristic role: Vocal / Drums / Bass / ...
    volume: Optional[float] = None  # linear gain as stored by REAPER (1.0 == unity)
    # Convenience: fader volume in dB. Fader trim only — excludes pan-law
    # attenuation and width, which REAPER applies separately.
    volume_db: Optional[float] = None
    pan: Optional[float] = None  # -1.0 (L) .. +1.0 (R)
    pan_mode: Optional[int] = None  # SDK I_PANMODE: 0=classic, 3=new balance, 5=stereo pan, 6=dual pan
    pan_law: Optional[float] = None  # SDK D_PANLAW: <0 = project default, 1.0 = +0dB
    width: Optional[float] = None  # SDK D_WIDTH: -1..1 (stereo width)
    mute: Optional[bool] = None
    solo: Optional[bool] = None
    # Raw solo state (SDK I_SOLO): 0=off, 1=solo, 2=solo in place,
    # 5=safe solo, 6=safe solo in place. ``solo`` is its boolean projection.
    solo_mode: Optional[int] = None
    solo_defeat: Optional[bool] = None  # SDK B_SOLO_DEFEAT: audible even when another track is soloed
    main_send: Optional[bool] = None  # SDK B_MAINSEND: track sends audio to its parent/master
    color: Optional[str] = None  # "#rrggbb" when decodable and flagged as in use
    media_items: List[MediaItemState] = Field(default_factory=list)
    fx: List[FxState] = Field(default_factory=list)
    raw_lines: List[str] = Field(default_factory=list)


class ProjectState(BaseModel):
    """The top-level parsed project."""

    project_name: Optional[str] = None
    source_file: Optional[str] = None
    # Version/platform token from the <REAPER_PROJECT header (e.g. "7.0/win64").
    # Used to disambiguate the OS-dependent track-colour byte order.
    header_platform: Optional[str] = None
    tempo: Optional[float] = None
    time_sig_num: Optional[int] = None  # e.g. 4 in 4/4 (project default time signature)
    time_sig_denom: Optional[int] = None
    sample_rate: Optional[int] = None
    # Whether the stored sample rate is actually enforced ("use project sample
    # rate" checkbox); when False the stored rate is informational only.
    sample_rate_use: Optional[bool] = None
    tracks: List[TrackState] = Field(default_factory=list)
    routes: List[RouteState] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # -- convenience accessors -------------------------------------------------
    @property
    def media_items(self) -> List[MediaItemState]:
        items: List[MediaItemState] = []
        for track in self.tracks:
            items.extend(track.media_items)
        return items

    @property
    def fx(self) -> List[FxState]:
        processors: List[FxState] = []
        for track in self.tracks:
            processors.extend(track.fx)
        return processors


class AudioDescriptorSet(BaseModel):
    """Simple acoustic descriptors for one audio file.

    Computed with ``librosa`` by default. When the audio backend is unavailable or
    a file cannot be read, ``available`` is ``False`` and ``unavailable_reason``
    explains why, so the rest of the pipeline can continue uninterrupted.
    """

    node_id: Optional[str] = None  # graph node id of the associated audio_file
    file_path: Optional[str] = None
    available: bool = False
    unavailable_reason: Optional[str] = None

    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    rms_mean: Optional[float] = None
    rms_std: Optional[float] = None
    spectral_centroid_mean: Optional[float] = None
    spectral_bandwidth_mean: Optional[float] = None
    spectral_rolloff_mean: Optional[float] = None
    zero_crossing_rate_mean: Optional[float] = None
    tempo_estimate: Optional[float] = None
    onset_strength_mean: Optional[float] = None
    dynamic_range_db: Optional[float] = None  # approximation (peak vs noise floor)
    peak_amplitude: Optional[float] = None
    integrated_loudness_lufs: Optional[float] = None  # via pyloudnorm if available

    # Optional high-level descriptors contributed by an Essentia adapter, if present.
    extra: dict = Field(default_factory=dict)


class Recommendation(BaseModel):
    """An explainable, graph-derived suggestion.

    Every recommendation carries an explicit ``caveat`` to preserve producer agency:
    these are heuristics meant to support reflection, not objective mixing rules.
    """

    id: str
    title: str
    severity: Severity = "suggestion"
    confidence: float = 0.5
    related_node_ids: List[str] = Field(default_factory=list)
    explanation: str = ""
    suggested_action: str = ""
    caveat: str = "This is a graph-based heuristic, not an objective mixing rule."
    # Literature grounding: citations into the official REAPER guides backing
    # the suggested action (e.g. "REAPER User Guide, §2.14, pp. 43-44").
    references: List[str] = Field(default_factory=list)
