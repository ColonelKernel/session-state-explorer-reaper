"""Tests for the heuristic recommendation engine."""

from __future__ import annotations

from session_state_explorer.graph_builder import build_graph
from session_state_explorer.models import AudioDescriptorSet
from session_state_explorer.recommendations import generate_recommendations
from session_state_explorer.rpp_parser import parse_rpp


def _ids(recs):
    return {r.id for r in recs}


def test_vocal_without_fx_produces_vocal_chain_recommendation():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Lead Vox"
  >
>
"""
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    assert any(r.id.startswith("rec-vocal-chain") for r in recs)
    # Every recommendation must carry a caveat (producer agency).
    assert all(r.caveat for r in recs)


def test_many_tracks_without_routes_produces_bus_recommendation():
    tracks = "\n".join(
        f'  <TRACK\n    NAME "Track {i}"\n  >' for i in range(9)
    )
    rpp = f'<REAPER_PROJECT 0.1 "x" 0\n{tracks}\n>\n'
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    assert "rec-missing-bus" in _ids(recs)


def test_ambience_fx_without_shared_send_produces_ambience_bus_recommendation():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Snare"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaVerbate (Cockos)" v.dll 0 "" 0
      >
    >
  >
  <TRACK
    NAME "Guitar"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaDelay (Cockos)" d.dll 0 "" 0
      >
    >
  >
>
"""
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    assert "rec-ambience-bus" in _ids(recs)


def test_dense_fx_chain_recommendation():
    fx_lines = "\n".join(
        '      BYPASS 0 0 0\n'
        f'      <VST "VST: Plug{i} (X)" p.dll 0 "" 0\n      >'
        for i in range(7)
    )
    rpp = f"""<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Synth"
    <FXCHAIN
{fx_lines}
    >
  >
>
"""
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    assert any(r.id.startswith("rec-dense-fx") for r in recs)


def test_level_imbalance_recommendation():
    descriptors = [
        AudioDescriptorSet(node_id="audio-0", file_path="a.wav", available=True,
                           rms_mean=0.1, peak_amplitude=0.2),
        AudioDescriptorSet(node_id="audio-1", file_path="b.wav", available=True,
                           rms_mean=0.1, peak_amplitude=0.2),
        AudioDescriptorSet(node_id="audio-2", file_path="hot.wav", available=True,
                           rms_mean=0.9, peak_amplitude=0.95),
    ]
    # Minimal project; the rule only needs the descriptors.
    project = parse_rpp('<REAPER_PROJECT 0.1 "x" 0\n>\n')
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, descriptors)
    imbalance = [r for r in recs if r.id.startswith("rec-level-imbalance")]
    assert len(imbalance) == 1
    assert imbalance[0].related_node_ids == ["audio-2"]


def test_level_imbalance_aggregates_multiple_hot_files():
    # Several hot stems must yield ONE aggregated recommendation, not one card
    # per file (observed as recommendation spam on a real 23-stem session).
    descriptors = [
        AudioDescriptorSet(node_id=f"audio-{i}", file_path=f"q{i}.wav", available=True,
                           rms_mean=0.1, peak_amplitude=0.2)
        for i in range(3)
    ] + [
        AudioDescriptorSet(node_id="audio-hot1", file_path="hot1.wav", available=True,
                           rms_mean=0.9, peak_amplitude=0.95),
        AudioDescriptorSet(node_id="audio-hot2", file_path="hot2.wav", available=True,
                           rms_mean=0.8, peak_amplitude=0.9),
    ]
    project = parse_rpp('<REAPER_PROJECT 0.1 "x" 0\n>\n')
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, descriptors)
    imbalance = [r for r in recs if r.id.startswith("rec-level-imbalance")]
    assert len(imbalance) == 1
    assert set(imbalance[0].related_node_ids) == {"audio-hot1", "audio-hot2"}
    assert "2 audio items" in imbalance[0].explanation


def test_well_structured_session_produces_no_false_positives():
    # A vocal with a full chain, an ambience return that receives a send, few tracks.
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Lead Vox"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaEQ (Cockos)" e.dll 0 "" 0
      >
      BYPASS 0 0 0
      <VST "VST: ReaComp (Cockos)" c.dll 0 "" 0
      >
    >
    AUXRECV 1 0 1 0 0 0 0
  >
  <TRACK
    NAME "Reverb Return"
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaVerbate (Cockos)" v.dll 0 "" 0
      >
    >
  >
>
"""
    project = parse_rpp(rpp)
    graph = build_graph(project)
    recs = generate_recommendations(project, graph, [])
    ids = _ids(recs)
    assert "rec-ambience-bus" not in ids  # a shared ambience return exists
    assert "rec-missing-bus" not in ids  # routes exist and few tracks
    assert not any(i.startswith("rec-vocal-chain") for i in ids)  # full vocal chain
