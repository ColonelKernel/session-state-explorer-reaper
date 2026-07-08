"""The lossless gate plus golden structural facts for the demo project.

Relocated from the analyzer repo (origin ``SessionStateExplorer@041f529``,
``tests/drivers/reaper/test_lossless_roundtrip.py``), re-pointed at
``session_state_explorer.canonical_export.mapper``.

``to_native(to_canonical(p)).model_dump() == p.model_dump()`` is the adapter's
losslessness contract; the golden-snapshot assertions pin the canonical
projection of ``data/examples/example_project.rpp`` so schema drift is caught
structurally.

The analyzer original's fingerprint and driver-registry tests were not
relocated: fingerprints are covered by this repo's own ``test_fingerprint.py``
and the driver registry stayed in the analyzer (and is deleted there at P2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# The canonical-export feature needs the (non-PyPI) contract package; skip this
# whole module cleanly when it is absent so the rest of the suite still runs.
pytest.importorskip("canonical_snapshot")

from canonical_snapshot.nested import NativePayload  # noqa: E402
from session_state_explorer.canonical_export.mapper import (  # noqa: E402
    to_canonical,
    to_native,
)
from session_state_explorer.rpp_parser import parse_rpp  # noqa: E402

EXAMPLE_RPP = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "examples"
    / "example_project.rpp"
)


@pytest.fixture(scope="module")
def example_project():
    text = EXAMPLE_RPP.read_text(encoding="utf-8")
    return parse_rpp(text, source_file=str(EXAMPLE_RPP))


def test_example_project_exists():
    assert EXAMPLE_RPP.exists()


def test_lossless_roundtrip(example_project):
    session = to_canonical(example_project)
    assert to_native(session).model_dump() == example_project.model_dump()


def test_to_native_requires_native_payload(example_project):
    session = to_canonical(example_project)
    session.native = None
    with pytest.raises(ValueError):
        to_native(session)


def test_to_native_rejects_foreign_payload(example_project):
    session = to_canonical(example_project)
    session.native = NativePayload(dialect="ableton", model_name="LiveSet", model={})
    with pytest.raises(ValueError):
        to_native(session)


def test_golden_structural_facts(example_project):
    session = to_canonical(example_project)

    assert session.dialect == "reaper"
    assert session.name == "example_project"
    assert session.tempo == 120.0
    assert session.time_signature == "4/4"
    assert session.sample_rate == 44100
    assert session.extras["header_platform"] == "7.0/win64"
    assert session.extras["sample_rate_use"] is False
    assert session.metadata["source_artifact"] == "rpp_file"

    assert len(session.tracks) == 9
    assert session.tracks[0].name == "Lead Vox"
    assert session.tracks[0].id == "reaper:track-0"
    assert all(t.id.startswith("reaper:") for t in session.tracks)

    processors = session.all_processors()
    assert len(processors) == 22
    assert all(p.id.startswith("reaper:") for p in processors)

    assert len(session.routes) == 4
    assert sum(1 for r in session.routes if r.route_type == "send") == 3
    assert sum(1 for r in session.routes if r.route_type == "unresolved") == 1
    assert all(r.id.startswith("reaper:") for r in session.routes)

    clips = session.all_clips()
    assert len(clips) == 7  # Synth Pad and Drum Bus carry no media items
    assert all(c.clip_type == "audio" for c in clips)
    assert clips[0].audio_file == "audio/lead_vox.wav"
    assert clips[0].position_seconds == 0.0
    assert clips[0].length_seconds == 2.0

    # Native payload is intact and native ids inside it stay un-namespaced.
    assert session.native is not None
    assert session.native.dialect == "reaper"
    assert session.native.model_name == "ProjectState"
    assert session.native.model["tracks"][0]["id"] == "track-0"

    # The heuristic role carries inferred provenance; the track itself is observed.
    lead = session.tracks[0]
    assert lead.role == "Vocal"
    assert lead.provenance.observability == "observed"
    assert lead.provenance.source_artifact == "rpp_file"
    assert lead.field_provenance["role"].observability == "inferred"

    # REAPER-only mixer state is surfaced in extras without schema changes.
    assert lead.extras["volume"] == 1.0


# ---------------------------------------------------------------------------
# Folder hierarchy + per-send channel mapping (tests/fixtures fixture)
# ---------------------------------------------------------------------------

FOLDER_SENDS_RPP = (
    Path(__file__).resolve().parent / "fixtures" / "folder_sends_project.rpp"
)


@pytest.fixture(scope="module")
def folder_sends_session():
    text = FOLDER_SENDS_RPP.read_text(encoding="utf-8")
    project = parse_rpp(text, source_file=str(FOLDER_SENDS_RPP))
    return to_canonical(project)


def test_folder_fixture_roundtrip_is_lossless(folder_sends_session):
    text = FOLDER_SENDS_RPP.read_text(encoding="utf-8")
    project = parse_rpp(text, source_file=str(FOLDER_SENDS_RPP))
    assert to_native(to_canonical(project)).model_dump() == project.model_dump()


def test_folder_parents_become_group_tracks(folder_sends_session):
    tracks = {t.name: t for t in folder_sends_session.tracks}
    drum_bus, room = tracks["Drum Bus"], tracks["Room"]
    assert drum_bus.kind == "group"
    assert drum_bus.group_id is None
    assert drum_bus.sums_children is True
    # The summing claim is behavioural REAPER knowledge, not a stored field.
    assert drum_bus.field_provenance["sums_children"].observability == "inferred"
    # A nested folder parent is a group AND a child of the outer folder.
    assert room.kind == "group"
    assert room.group_id == drum_bus.id


def test_folder_children_carry_inferred_group_id(folder_sends_session):
    tracks = {t.name: t for t in folder_sends_session.tracks}
    kick, room_l, verb = tracks["Kick"], tracks["Room L"], tracks["Verb"]
    assert kick.kind == "audio"
    assert kick.group_id == tracks["Drum Bus"].id
    # The parent link is derived from ISBUS depth deltas -> inferred, with the
    # raw observed ISBUS values riding in extras.
    prov = kick.field_provenance["group_id"]
    assert prov.observability == "inferred"
    assert "ISBUS" in (prov.explanation or "")
    assert kick.extras["folder_state"] == 0
    assert kick.extras["folder_depth"] == 0
    assert room_l.group_id == tracks["Room"].id
    # ISBUS -2 closed both folder levels: the next track is top-level again.
    assert verb.group_id is None


def test_folder_child_with_main_send_off_is_flagged(folder_sends_session):
    tracks = {t.name: t for t in folder_sends_session.tracks}
    room_l = tracks["Room L"]
    assert room_l.extras["main_send"] is False
    assert any("MAINSEND" in w for w in room_l.warnings)
    # Children that DO feed their parent are not flagged.
    assert tracks["Kick"].warnings == []


def test_send_channel_mapping_is_decoded(folder_sends_session):
    routes = {
        (r.source_track_id, r.target_track_id): r
        for r in folder_sends_session.routes
    }
    tracks = {t.name: t.id for t in folder_sends_session.tracks}

    # Kick -> Verb: stereo pickup from channels 3/4 into channels 5/6,
    # MIDI disabled (I_MIDIFLAGS low bits == 31).
    stereo = routes[(tracks["Kick"], tracks["Verb"])]
    assert stereo.source_channels == [2, 3]
    assert stereo.target_channels == [4, 5]
    assert stereo.channel_count == 2
    assert stereo.channel_layout == "stereo"
    assert stereo.extras["src_channel"] == 2
    assert stereo.extras["dst_channel"] == 4
    assert stereo.extras["audio_enabled"] is True
    assert stereo.extras["midi_enabled"] is False
    # The route stays observed; the decode is explained on its provenance.
    assert stereo.provenance.observability == "observed"
    assert "I_SRCCHAN" in (stereo.provenance.explanation or "")

    # Room -> Verb: 4-channel send (I_SRCCHAN mode 2).
    wide = routes[(tracks["Room"], tracks["Verb"])]
    assert wide.source_channels == [0, 1, 2, 3]
    assert wide.target_channels == [0, 1, 2, 3]
    assert wide.channel_count == 4
    assert wide.channel_layout == "4ch"

    # Kick -> Mono FX: mono pickup from channel 3 into mono channel 6,
    # MIDI all channels -> keep source channel.
    mono = routes[(tracks["Kick"], tracks["Mono FX"])]
    assert mono.source_channels == [2]
    assert mono.target_channels == [5]
    assert mono.channel_count == 1
    assert mono.channel_layout == "mono"
    assert mono.extras["midi_enabled"] is True
    assert mono.extras["midi_source_channel"] == "all"
    assert mono.extras["midi_target_channel"] == "source"


def test_midi_only_send_gets_no_audio_channel_spec(folder_sends_session):
    tracks = {t.name: t.id for t in folder_sends_session.tracks}
    routes = {
        (r.source_track_id, r.target_track_id): r
        for r in folder_sends_session.routes
    }
    midi_only = routes[(tracks["Drum Bus"], tracks["MIDI Target"])]
    assert midi_only.source_channels is None
    assert midi_only.target_channels is None
    assert midi_only.channel_count is None
    assert midi_only.channel_layout is None
    assert midi_only.extras["audio_enabled"] is False
    assert midi_only.extras["midi_enabled"] is True

    # A short AUXRECV line (no channel tokens) stays stereo-implicit: all
    # channel fields None and no invented extras.
    short = routes[(tracks["Verb"], tracks["MIDI Target"])]
    assert short.source_channels is None
    assert short.channel_count is None
    assert "audio_enabled" not in short.extras
    assert short.provenance.explanation is None
