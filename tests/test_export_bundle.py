"""End-to-end tests for the canonical 5-file bundle exporter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

# The exporter transitively imports the (non-PyPI) contract package; skip this
# whole module cleanly when it is absent so the rest of the suite still runs.
pytest.importorskip("canonical_snapshot")

from session_state_explorer.canonical_export.exporter import (  # noqa: E402
    BUNDLE_FILES,
    export_bundle,
)

EXAMPLE_RPP = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "examples"
    / "example_project.rpp"
)


@pytest.fixture(scope="module")
def bundle(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("bundle")
    result = export_bundle(EXAMPLE_RPP, out_dir)
    return out_dir, result


def _load(out_dir: Path, name: str):
    return json.loads((out_dir / name).read_text(encoding="utf-8"))


def test_all_five_bundle_files_are_written(bundle):
    out_dir, result = bundle
    assert set(BUNDLE_FILES) == {
        "adapter_descriptor.json",
        "capabilities.json",
        "native.json",
        "canonical.snapshot.json",
        "validation.json",
    }
    for name in BUNDLE_FILES:
        assert (out_dir / name).is_file(), name
    assert result["valid"] is True


def test_validation_report_is_valid(bundle):
    out_dir, _ = bundle
    report = _load(out_dir, "validation.json")
    assert report["valid"] is True
    assert report["errors"] == []
    assert report["stats"]["entities"] > 0


def test_snapshot_has_track_channel_split(bundle):
    out_dir, _ = bundle
    snapshot = _load(out_dir, "canonical.snapshot.json")
    types = {e["entity_type"] for e in snapshot["entities"]}
    assert "PROJECT" in types
    assert "TRACK" in types
    assert "CHANNEL" in types
    rel_types = {r["rel_type"] for r in snapshot["relationships"]}
    assert "TRACK_USES_CHANNEL" in rel_types
    # REAPER fuses lane and signal path: every TRACK emits its CHANNEL half.
    tracks = [e for e in snapshot["entities"] if e["entity_type"] == "TRACK"]
    used = {
        r["source"]
        for r in snapshot["relationships"]
        if r["rel_type"] == "TRACK_USES_CHANNEL"
    }
    assert {t["id"] for t in tracks} == used


def test_native_hash_matches_extensions_ref(bundle):
    out_dir, result = bundle
    snapshot = _load(out_dir, "canonical.snapshot.json")
    ref = snapshot["extensions"]["reaper"]["native_file"]
    assert ref["path"] == "native.json"
    actual = hashlib.sha256((out_dir / "native.json").read_bytes()).hexdigest()
    # native_sha256 is the integrity hash of native.json exactly as written.
    assert ref["sha256"] == actual == result["native_sha256"]
    # snapshot_id is content-addressed but decoupled from the native file hash
    # (which embeds the machine-specific path), so it is NOT native_sha256[:16].
    sid = snapshot["snapshot_id"]
    assert sid.startswith("reaper:rpp:")
    assert len(sid.split(":")[-1]) == 16


def test_snapshot_id_is_stable_across_file_location(tmp_path):
    # The same .rpp content exported from two different directories must yield
    # the same snapshot_id — it must not fold in the containing path.
    content = EXAMPLE_RPP.read_bytes()
    a = tmp_path / "machineA" / "Users" / "alice" / "proj"
    b = tmp_path / "machineB" / "Users" / "bob" / "proj"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    (a / "example_project.rpp").write_bytes(content)
    (b / "example_project.rpp").write_bytes(content)
    ra = export_bundle(a / "example_project.rpp", tmp_path / "outA")
    rb = export_bundle(b / "example_project.rpp", tmp_path / "outB")
    assert ra["snapshot_id"] == rb["snapshot_id"]


def test_sanitization_redacts_posix_and_windows_home_paths(tmp_path):
    rpp = (
        '<REAPER_PROJECT 0.1 "7.0/win64" 0\n'
        '  <TRACK\n    NAME "Vox"\n    <ITEM\n'
        '      <SOURCE WAVE\n        FILE "C:\\Users\\jsmith\\Music\\vox.wav"\n      >\n'
        "    >\n  >\n"
        '  <TRACK\n    NAME "Gtr"\n    <ITEM\n'
        '      <SOURCE WAVE\n        FILE "/Users/alice/Audio/gtr.wav"\n      >\n'
        "    >\n  >\n>\n"
    )
    src = tmp_path / "proj.rpp"
    src.write_text(rpp)
    out = tmp_path / "out"
    export_bundle(src, out)  # sanitize=True by default
    for name in ("native.json", "canonical.snapshot.json"):
        text = (out / name).read_text(encoding="utf-8")
        assert "jsmith" not in text, name  # Windows user name redacted
        assert "alice" not in text, name  # POSIX user name redacted


def test_sanitization_leaves_nested_users_segment_intact(tmp_path):
    # A path where 'Users' is nested under other dirs (a network mount) is not a
    # home root and must not be corrupted.
    rpp = (
        '<REAPER_PROJECT 0.1 "7.0/win64" 0\n'
        '  <TRACK\n    NAME "Vox"\n    <ITEM\n'
        '      <SOURCE WAVE\n        FILE "/mnt/backups/Users/carol/mix.wav"\n      >\n'
        "    >\n  >\n>\n"
    )
    src = tmp_path / "proj.rpp"
    src.write_text(rpp)
    out = tmp_path / "out"
    export_bundle(src, out)
    native = (out / "native.json").read_text(encoding="utf-8")
    assert "/mnt/backups/Users/carol/mix.wav" in native  # untouched, not "~"-fused


def test_created_at_override_neutralizes_mtime_nondeterminism(tmp_path):
    # Re-exporting the SAME file after its mtime changes (e.g. a git checkout)
    # is byte-identical when created_at is pinned, and differs when it is not.
    import os

    src = tmp_path / "proj.rpp"
    src.write_bytes(EXAMPLE_RPP.read_bytes())
    ts = "2020-01-01T00:00:00+00:00"
    export_bundle(src, tmp_path / "o1", created_at=ts)
    os.utime(src, (1_000_000_000, 1_000_000_000))  # change mtime
    export_bundle(src, tmp_path / "o2", created_at=ts)
    for name in BUNDLE_FILES:
        assert (tmp_path / "o1" / name).read_bytes() == (tmp_path / "o2" / name).read_bytes(), name

    # Without the pin, the mtime change leaks into created_at (non-reproducible).
    os.utime(src, (2_000_000_000, 2_000_000_000))
    export_bundle(src, tmp_path / "o3")
    snap1 = json.loads((tmp_path / "o1" / "canonical.snapshot.json").read_text())
    snap3 = json.loads((tmp_path / "o3" / "canonical.snapshot.json").read_text())
    assert snap1["created_at"] != snap3["created_at"]
    assert snap1["snapshot_id"] == snap3["snapshot_id"]  # id is content-addressed, still stable


def test_no_home_dir_paths_in_canonical_json(bundle):
    out_dir, _ = bundle
    for name in ("canonical.snapshot.json", "native.json"):
        text = (out_dir / name).read_text(encoding="utf-8")
        assert "/Users/" not in text, name
        assert "/home/" not in text, name
        assert str(Path.home()) not in text, name


def test_provenance_resolves_and_source_is_honest(bundle):
    out_dir, _ = bundle
    snapshot = _load(out_dir, "canonical.snapshot.json")
    assert snapshot["schema_version"].startswith("0.2")
    assert snapshot["source"]["daw"] == "reaper"
    assert snapshot["source"]["adapter"] == "session-state-explorer-reaper"
    assert snapshot["source"]["capture_modes"] == ["file_parse"]
    assert snapshot["source"]["daw_version"] == "7.0"  # from the .rpp header
    prov_ids = {p["id"] for p in snapshot["provenance"]}
    for entity in snapshot["entities"]:
        for ref in entity["prov"].values():
            assert ref in prov_ids
    # created_at derives from the file mtime, not now(): deterministic.
    assert snapshot["created_at"]
    evidences = {p["evidence"] for p in snapshot["provenance"]}
    assert "OBSERVED" in evidences
    assert "INFERRED" in evidences  # heuristic track roles


def test_export_is_deterministic(bundle, tmp_path):
    out_dir, _ = bundle
    second = tmp_path / "again"
    export_bundle(EXAMPLE_RPP, second)
    for name in BUNDLE_FILES:
        assert (second / name).read_bytes() == (out_dir / name).read_bytes(), name


def test_capabilities_and_descriptor_are_honest(bundle):
    out_dir, _ = bundle
    caps = _load(out_dir, "capabilities.json")
    assert set(caps["read"]) >= {"structure", "channel", "routing", "processing"}
    # write / live_observation / render are empty: support NONE, stated.
    assert caps["write"] == {}
    assert caps["live_observation"] == {}
    assert caps["render"] == {}
    plugin_state = caps["read"]["processing"]["fields"]["plugin_internal_state"]
    assert plugin_state["support"] == "NONE"
    descriptor = _load(out_dir, "adapter_descriptor.json")
    assert descriptor["adapter_id"] == "reaper-rpp"
    assert descriptor["known_limitations"]


# ---------------------------------------------------------------------------
# Folder hierarchy + per-send channel mapping in the flat v0.2 snapshot
# ---------------------------------------------------------------------------

FOLDER_SENDS_RPP = (
    Path(__file__).resolve().parent / "fixtures" / "folder_sends_project.rpp"
)


@pytest.fixture(scope="module")
def folder_bundle(tmp_path_factory):
    out_dir = tmp_path_factory.mktemp("folder_bundle")
    result = export_bundle(FOLDER_SENDS_RPP, out_dir)
    return out_dir, result


def test_folder_bundle_is_valid(folder_bundle):
    _, result = folder_bundle
    assert result["valid"] is True
    assert result["errors"] == []


def test_folder_hierarchy_lands_as_contains_and_gated_sums(folder_bundle):
    out_dir, _ = folder_bundle
    snapshot = _load(out_dir, "canonical.snapshot.json")
    rels = snapshot["relationships"]

    def rel_set(rel_type, prop_filter=None):
        return {
            (r["source"], r["target"])
            for r in rels
            if r["rel_type"] == rel_type
            and (prop_filter is None or all(
                r["properties"].get(k) == v for k, v in prop_filter.items()
            ))
        }

    # Containment is unconditional and TRACK-level (group_member kind).
    contains = rel_set("CONTAINS", {"kind": "group_member"})
    assert ("reaper:track-0", "reaper:track-1") in contains  # Drum Bus > Kick
    assert ("reaper:track-0", "reaper:track-2") in contains  # Drum Bus > Room
    assert ("reaper:track-2", "reaper:track-3") in contains  # Room > Room L
    # Top-level tracks are not contained by anything.
    contained_children = {dst for _, dst in contains}
    assert "reaper:track-4" not in contained_children  # Verb (after ISBUS -2)

    # REAPER folder parents are summing buses: the group sum is expressed on
    # the CHANNEL side, gated by sums_children (grouping honesty).
    sums = rel_set("SUMS_TO")
    assert ("reaper:track-1:channel", "reaper:track-0:channel") in sums
    assert ("reaper:track-3:channel", "reaper:track-2:channel") in sums
    routes_via_group = rel_set("CHANNEL_ROUTES_TO", {"via": "group_sum"})
    assert ("reaper:track-1:channel", "reaper:track-0:channel") in routes_via_group

    # The folder parent's TRACK half carries the folder semantics.
    entities = {e["id"]: e for e in snapshot["entities"]}
    drum_bus = entities["reaper:track-0"]
    assert "folder_parent" in drum_bus["semantic_roles"]
    assert "submix" in drum_bus["semantic_roles"]

    # A child whose MAINSEND is off is flagged in the snapshot warnings (the
    # contract gates summing per parent, so the edge itself remains).
    assert any(
        "reaper:track-3" in w and "MAINSEND" in w for w in snapshot["warnings"]
    )


def test_send_channel_mapping_rides_the_sends_edges(folder_bundle):
    out_dir, _ = folder_bundle
    snapshot = _load(out_dir, "canonical.snapshot.json")
    sends = {
        (r["source"], r["target"]): r["properties"]
        for r in snapshot["relationships"]
        if r["rel_type"] == "CHANNEL_SENDS_TO"
    }

    # Kick -> Verb: decoded channel lists plus the raw packed bitfields.
    stereo = sends[("reaper:track-1:channel", "reaper:track-4:channel")]
    assert stereo["source_channels"] == [2, 3]
    assert stereo["target_channels"] == [4, 5]
    assert stereo["channel_count"] == 2
    assert stereo["channel_layout"] == "stereo"
    assert stereo["src_channel"] == 2 and stereo["dst_channel"] == 4
    assert stereo["midi_enabled"] is False

    # Kick -> Mono FX: mono downmix destination.
    mono = sends[("reaper:track-1:channel", "reaper:track-5:channel")]
    assert mono["source_channels"] == [2]
    assert mono["target_channels"] == [5]
    assert mono["channel_layout"] == "mono"

    # Drum Bus -> MIDI Target: MIDI-only, no invented audio channel spec.
    midi_only = sends[("reaper:track-0:channel", "reaper:track-6:channel")]
    assert "source_channels" not in midi_only
    assert midi_only["audio_enabled"] is False
    assert midi_only["midi_enabled"] is True

    # Short AUXRECV (Verb -> MIDI Target): stereo-implicit, no channel keys.
    short = sends[("reaper:track-4:channel", "reaper:track-6:channel")]
    assert "source_channels" not in short
    assert "channel_count" not in short
