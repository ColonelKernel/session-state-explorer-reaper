"""The honest capability manifest for the REAPER ``.rpp`` file-parse pathway.

A capability manifest states what this adapter's pathways can even *attempt*
to observe — separate from what any one capture actually yielded (that is the
snapshot's ``coverage``). Read, write, live observation, and render are
SEPARATE modes: being able to parse a value out of a project file implies
nothing about writing it back.

Honesty rules applied here:

- The ``.rpp`` text format is community/SDK documented, not an official spec:
  everything parsed is ``COMMUNITY_DOCUMENTED``.
- ``validation_status`` is ``TESTED`` only for fields the test suite actually
  exercises against REAPER 7 fixtures; heuristics are labelled ``HEURISTIC``
  stability.
- Plug-in internal state is *applicable but unsupported*: the base64 chunk
  blobs are present in the file and deliberately not decoded — INACCESSIBLE,
  stated in ``known_limitations``.
- Automation envelopes, take FX, item fades, and the tempo map are parseable
  in principle but unsupported today: support ``NONE``, not silence.
- ``write`` / ``live_observation`` / ``render`` are empty (support NONE):
  runtime observation of a live REAPER instance is future work.
"""

from __future__ import annotations

from typing import Optional

from canonical_snapshot import (
    AdapterDescriptor,
    CapabilityManifest,
    DomainCapability,
    FieldCapability,
)

ADAPTER_ID = "reaper-rpp"
ADAPTER_NAME = "session-state-explorer-reaper"
DAW = "reaper"
CAPTURE_MODES = ["file_parse"]
TESTED_DAW_VERSION = "7.0"

KNOWN_LIMITATIONS = [
    "Plug-in internal state (VST/AU/JS chunk blobs) is present in the .rpp "
    "but not decoded: plug-in parameters are INACCESSIBLE through this pathway.",
    "Automation envelopes, take FX, item fades, and the tempo map are not "
    "parsed (UNSUPPORTED); only the project-default tempo and time signature "
    "are observed.",
    "Folder hierarchy is reconstructed from ISBUS depth deltas (derived, not "
    "a stored parent pointer). Group summing is gated per folder parent: a "
    "child whose MAINSEND is disabled does not actually feed its parent and "
    "is flagged with a warning rather than suppressing the group-sum edge.",
    "Track colour byte order is OS-dependent; decoding relies on the project "
    "header platform token and falls back to the Windows layout with a warning.",
    "Track roles and FX families are heuristics (name keywords plus a "
    "guide-derived stock-FX knowledge table), never DAW ground truth.",
    "No write-back, live observation, or render capability; runtime "
    "observation of a live REAPER instance is future work.",
]

_NOTES = [
    "Capabilities describe the .rpp file-parse pathway only.",
    "The .rpp format knowledge is community/SDK documented "
    "(COMMUNITY_DOCUMENTED), not an official file-format specification.",
    "validation_status=TESTED means the field is exercised by this repo's "
    "test suite against REAPER 7 fixtures, including the lossless "
    "round-trip gate.",
]


def _observed(support: str = "FULL", validation: str = "TESTED") -> FieldCapability:
    """A field parsed directly out of the .rpp text."""

    return FieldCapability(
        applicability="APPLICABLE",
        support=support,  # type: ignore[arg-type]
        capture_method="rpp_parse",
        source_stability="COMMUNITY_DOCUMENTED",
        tested_daw_version=TESTED_DAW_VERSION,
        validation_status=validation,  # type: ignore[arg-type]
    )


def _heuristic(capture_method: str) -> FieldCapability:
    """A field derived by a name/keyword heuristic (tested, but heuristic)."""

    return FieldCapability(
        applicability="APPLICABLE",
        support="PARTIAL",
        capture_method=capture_method,
        source_stability="HEURISTIC",
        tested_daw_version=TESTED_DAW_VERSION,
        validation_status="TESTED",
    )


def _unsupported() -> FieldCapability:
    """Applicable REAPER state this pathway does not observe at all."""

    return FieldCapability(
        applicability="APPLICABLE",
        support="NONE",
        validation_status="UNTESTED",
    )


def build_capability_manifest(
    daw_version: Optional[str] = None, adapter_version: str = ""
) -> CapabilityManifest:
    """Build the read-pathway capability manifest for this adapter."""

    read = {
        "structure": DomainCapability(
            fields={
                "tracks": _observed(),
                "track_name": _observed(),
                "track_color": _observed(support="PARTIAL"),
                "track_role": _heuristic("name_keyword_heuristic"),
                "project_tempo": _observed(),
                "project_time_signature": _observed(),
                "project_sample_rate": _observed(),
                # Raw ISBUS folder state/depth is observed; the parent/child
                # structure itself is a deterministic derivation from those
                # deltas, so the snapshot marks it INFERRED per entity.
                "folder_hierarchy": _observed(),
            }
        ),
        "channel": DomainCapability(
            fields={
                "volume": _observed(),
                "pan": _observed(),
                "mute": _observed(),
                "solo": _observed(),
                "solo_mode": _observed(),
                "solo_defeat": _observed(),
                "pan_mode": _observed(),
                "pan_law": _observed(),
                "width": _observed(),
                "main_send": _observed(),
            }
        ),
        "routing": DomainCapability(
            fields={
                "sends": _observed(),
                "send_volume": _observed(),
                "send_pan": _observed(),
                "send_mute": _observed(),
                "send_mode": _observed(),
                # Per-send channel mapping (AUXRECV I_SRCCHAN/I_DSTCHAN
                # bitfields) and MIDI flags; PARTIAL because MIDI bus bits and
                # the fader-controls-MIDI flag are not decoded.
                "send_channels": _observed(),
                "send_midi_flags": _observed(support="PARTIAL"),
                "unresolved_sources": _observed(support="PARTIAL"),
                "hardware_outputs": _unsupported(),
            }
        ),
        "processing": DomainCapability(
            fields={
                "fx_chain": _observed(),
                "fx_bypass": _observed(),
                "fx_offline": _observed(),
                "fx_preset": _observed(),
                "record_input_fx": _observed(),
                "fx_family": _heuristic("fx_knowledge_and_keywords"),
                "fx_parameters": _unsupported(),
                "plugin_internal_state": _unsupported(),
            }
        ),
        "temporal": DomainCapability(
            fields={
                "media_items": _observed(),
                "item_position": _observed(),
                "item_length": _observed(),
                "item_source_file": _observed(),
                "item_source_type": _observed(),
                "take_fx": _unsupported(),
                "item_fades": _unsupported(),
            }
        ),
        "automation": DomainCapability(
            fields={
                "envelopes": _unsupported(),
                "tempo_map": _unsupported(),
            }
        ),
    }

    return CapabilityManifest(
        daw=DAW,
        daw_version=daw_version,
        adapter=ADAPTER_NAME,
        adapter_version=adapter_version,
        read=read,
        # write / live_observation / render deliberately empty: support NONE.
        notes=list(_NOTES),
    )


def build_adapter_descriptor() -> AdapterDescriptor:
    """Build the bundle-level identity card (``adapter_descriptor.json``)."""

    return AdapterDescriptor(
        adapter_id=ADAPTER_ID,
        daw=DAW,
        capture_modes=list(CAPTURE_MODES),
        read=(
            "Parses REAPER .rpp project files: structure (incl. folder "
            "hierarchy), channel state, routing (sends incl. per-send "
            "channel/MIDI mapping and unresolved sources), FX chains "
            "(incl. record-input chains), and media items. Plug-in internals "
            "hidden; automation unsupported."
        ),
        write="NONE",
        live_observation="NONE (runtime observation is future work)",
        render="NONE",
        known_limitations=list(KNOWN_LIMITATIONS),
    )
