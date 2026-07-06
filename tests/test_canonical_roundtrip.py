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
