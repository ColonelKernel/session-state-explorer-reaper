"""Lossless mapping between the native REAPER ``ProjectState`` and the nested canonical form.

Relocated from the analyzer repo (origin ``SessionStateExplorer@041f529``,
``src/session_explorer/drivers/reaper/mapper.py``); imports rewired to the
shared :mod:`canonical_snapshot` contract package (nested models + provenance
from ``canonical_snapshot.nested``, id namespacing from
``canonical_snapshot.ids``).

Losslessness contract (the round-trip gate):

    ``to_native(to_canonical(project)).model_dump() == project.model_dump()``

The complete native model rides along as ``session.native`` (a
:class:`~canonical_snapshot.nested.NativePayload`), so nothing the parser
observed can be dropped by the canonical projection. Canonical entity ids are
namespaced (``reaper:track-0``); the native ids inside the payload stay
untouched.

The nested :class:`~canonical_snapshot.nested.CanonicalSession` produced here
is an internal intermediate — it never appears on the wire. The exporter
flattens it through :func:`canonical_snapshot.flatten_session` into the flat
v0.2 ``CanonicalDAWSnapshot``.
"""

from __future__ import annotations

from os.path import basename, splitext
from typing import Any, Optional

from canonical_snapshot.ids import namespaced
from canonical_snapshot.nested import (
    CanonicalSession,
    Clip,
    NativePayload,
    Processor,
    Provenance,
    Route,
    Track,
    inferred,
)

from ..utils import (
    decode_send_dst_channels,
    decode_send_midi_flags,
    decode_send_src_channels,
)
from .native_models import (
    FxState,
    MediaItemState,
    ProjectState,
    RouteState,
    TrackState,
)

DIALECT = "reaper"
NATIVE_MODEL_NAME = "ProjectState"


def _ns(raw_id: Optional[str]) -> Optional[str]:
    return namespaced(DIALECT, raw_id) if raw_id is not None else None


def _observed(source_artifact: str) -> Provenance:
    # A fresh instance per entity: Provenance is a mutable model and must not
    # be aliased across entities.
    return Provenance(observability="observed", source_artifact=source_artifact)


def _non_none(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


# ---------------------------------------------------------------------------
# native -> canonical
# ---------------------------------------------------------------------------


def _clip_type(item: MediaItemState) -> str:
    if item.source_type == "MIDI":
        return "midi"
    if item.source_type:
        return "audio"
    return "unknown"


def _map_clip(item: MediaItemState, source_artifact: str) -> Clip:
    return Clip(
        id=_ns(item.id),
        track_id=_ns(item.track_id),
        name=item.name,
        clip_type=_clip_type(item),
        position_seconds=item.position,
        length_seconds=item.length,
        audio_file=item.source_file,
        source_type=item.source_type,
        provenance=_observed(source_artifact),
        raw_source=list(item.raw_lines),
    )


def _map_processor(fx: FxState, source_artifact: str) -> Processor:
    return Processor(
        id=_ns(fx.id),
        track_id=_ns(fx.track_id),
        index=fx.index,
        name=fx.name,
        kind=fx.fx_type,
        family=fx.family,
        enabled=fx.enabled,
        offline=fx.offline,
        chain=fx.chain,
        preset=fx.preset,
        provenance=_observed(source_artifact),
        raw_source=fx.raw_line,
    )


def _map_track(track: TrackState, source_artifact: str) -> Track:
    field_provenance = {}
    if track.role is not None:
        field_provenance["role"] = inferred(
            explanation=(
                f"Role inferred from the track name {track.name!r} by keyword "
                "matching; heuristic metadata, not DAW ground truth."
            ),
            confidence=0.6,
            source_artifact=source_artifact,
        )

    # Folder hierarchy. A positive ISBUS depth delta marks a folder parent —
    # in REAPER that is a real mixer track that also *sums* its children (the
    # contract's group-kind track), so both facts are stated with their own
    # evidence class: the raw ISBUS values are observed (they ride in extras),
    # while the parent link and the summing claim are derived.
    is_folder_parent = (track.folder_depth or 0) > 0
    sums_children: Optional[bool] = None
    warnings: list[str] = []
    if is_folder_parent:
        sums_children = True
        field_provenance["sums_children"] = inferred(
            explanation=(
                "A REAPER folder parent is a summing bus: children with their "
                "parent send enabled (MAINSEND) mix into the parent channel. "
                "Documented REAPER behaviour, not a stored field."
            ),
            confidence=0.9,
            source_artifact=source_artifact,
        )
    if track.parent_track_id is not None:
        field_provenance["group_id"] = inferred(
            explanation=(
                "Parent folder derived from the ISBUS folder-depth deltas "
                "across the ordered track list; deterministic reconstruction "
                "from observed structure — the .rpp stores no parent pointer."
            ),
            confidence=0.95,
            source_artifact=source_artifact,
        )
        if track.main_send is False:
            # The contract gates group summing per parent, not per child, so
            # this exception cannot suppress the child's group-sum edge; state
            # it as a warning instead of silently overclaiming signal flow.
            warnings.append(
                "main send (MAINSEND) is disabled: this track does not feed "
                "its folder parent's summing channel despite the folder "
                "membership."
            )

    return Track(
        id=_ns(track.id),
        index=track.index,
        name=track.name,
        kind="group" if is_folder_parent else "audio",
        role=track.role,
        color=track.color,
        volume_db=track.volume_db,
        pan=track.pan,
        mute=track.mute,
        solo=track.solo,
        group_id=_ns(track.parent_track_id),
        sums_children=sums_children,
        clips=[_map_clip(item, source_artifact) for item in track.media_items],
        processors=[_map_processor(fx, source_artifact) for fx in track.fx],
        provenance=_observed(source_artifact),
        field_provenance=field_provenance,
        extras=_non_none(
            volume=track.volume,
            pan_mode=track.pan_mode,
            pan_law=track.pan_law,
            width=track.width,
            solo_mode=track.solo_mode,
            solo_defeat=track.solo_defeat,
            main_send=track.main_send,
            folder_state=track.folder_state,
            folder_depth=track.folder_depth,
        ),
        raw_source=list(track.raw_lines),
        warnings=warnings,
    )


def _map_route(route: RouteState, source_artifact: str) -> Route:
    # Per-send channel mapping, decoded from the packed AUXRECV bitfields the
    # parser kept verbatim. The canonical fields carry the decoded 0-based
    # channel lists; the raw packed values ride in extras so the decode stays
    # auditable. All fields stay None (contract reading: stereo-implicit) when
    # the AUXRECV line predates / omits the channel tokens; a MIDI-only send
    # (src_channel == -1) gets no audio channel spec at all.
    source_channels = decode_send_src_channels(route.src_channel)
    target_channels = (
        decode_send_dst_channels(route.dst_channel, len(source_channels))
        if source_channels is not None
        else None
    )
    if target_channels is not None:
        channel_count = len(target_channels)
    elif source_channels is not None:
        channel_count = len(source_channels)
    else:
        channel_count = None
    channel_layout = None
    if channel_count == 1:
        channel_layout = "mono"
    elif channel_count == 2:
        channel_layout = "stereo"
    elif channel_count is not None:
        channel_layout = f"{channel_count}ch"

    extras = _non_none(
        src_channel=route.src_channel,
        dst_channel=route.dst_channel,
        midi_flags=route.midi_flags,
    )
    if route.src_channel is not None:
        extras["audio_enabled"] = route.src_channel != -1
    midi = decode_send_midi_flags(route.midi_flags)
    if midi is not None:
        extras["midi_enabled"] = midi["enabled"]
        if midi["enabled"]:
            extras["midi_source_channel"] = midi["source_channel"]
            extras["midi_target_channel"] = midi["target_channel"]

    provenance = _observed(source_artifact)
    if extras:
        provenance.explanation = (
            "Per-send channel/MIDI mapping decoded from the packed AUXRECV "
            "bitfields (SDK I_SRCCHAN/I_DSTCHAN/I_MIDIFLAGS); the raw packed "
            "values are preserved alongside the decoded channel lists."
        )

    return Route(
        id=_ns(route.id),
        source_track_id=_ns(route.source_track_id),
        source_name=route.source_name,
        target_track_id=_ns(route.target_track_id),
        target_name=route.target_name,
        route_type=route.route_type,
        send_mode=route.send_mode,
        volume=route.volume,
        volume_db=route.volume_db,
        pan=route.pan,
        mute=route.mute,
        source_channels=source_channels,
        target_channels=target_channels,
        channel_count=channel_count,
        channel_layout=channel_layout,
        provenance=provenance,
        extras=extras,
        raw_source=route.raw_line,
    )


def _session_name(project: ProjectState) -> str:
    if project.project_name:
        return project.project_name
    if project.source_file:
        stem = splitext(basename(project.source_file))[0]
        if stem:
            return stem
    return "Untitled Session"


def to_canonical(
    project: ProjectState, source_artifact: str = "rpp_file"
) -> CanonicalSession:
    """Project a native :class:`ProjectState` into a :class:`CanonicalSession`.

    The full native model is attached as ``session.native`` so the projection
    is lossless by construction.
    """

    time_signature = None
    if project.time_sig_num is not None and project.time_sig_denom is not None:
        time_signature = f"{project.time_sig_num}/{project.time_sig_denom}"

    return CanonicalSession(
        dialect=DIALECT,
        name=_session_name(project),
        source_file=project.source_file,
        tempo=project.tempo,
        time_signature=time_signature,
        sample_rate=project.sample_rate,
        tracks=[_map_track(track, source_artifact) for track in project.tracks],
        routes=[_map_route(route, source_artifact) for route in project.routes],
        warnings=list(project.warnings),
        metadata={"source_artifact": source_artifact},
        extras=_non_none(
            time_sig_num=project.time_sig_num,
            time_sig_denom=project.time_sig_denom,
            header_platform=project.header_platform,
            sample_rate_use=project.sample_rate_use,
        ),
        native=NativePayload(
            dialect=DIALECT,
            model_name=NATIVE_MODEL_NAME,
            model=project.model_dump(),
        ),
    )


# ---------------------------------------------------------------------------
# canonical -> native
# ---------------------------------------------------------------------------


def to_native(session: CanonicalSession) -> ProjectState:
    """Reconstruct the verbatim native :class:`ProjectState` from ``session.native``.

    Raises :class:`ValueError` when the payload is missing or belongs to a
    different dialect/model — a canonical session without its native payload
    cannot honestly claim to be a REAPER session.
    """

    native = session.native
    if native is None:
        raise ValueError(
            "Session carries no native payload; cannot reconstruct the REAPER "
            "ProjectState."
        )
    if native.dialect != DIALECT or native.model_name != NATIVE_MODEL_NAME:
        raise ValueError(
            f"Native payload is {native.dialect!r}/{native.model_name!r}; "
            f"expected {DIALECT!r}/{NATIVE_MODEL_NAME!r}."
        )
    return ProjectState.model_validate(native.model)
