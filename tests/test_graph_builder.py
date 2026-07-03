"""Tests for graph construction."""

from __future__ import annotations

from session_state_explorer.graph_builder import (
    PROJECT_NODE_ID,
    build_graph,
    graph_to_dict,
)
from session_state_explorer.rpp_parser import parse_rpp

RPP = """<REAPER_PROJECT 0.1 "x" 0
  TEMPO 120 4 4
  <TRACK
    NAME "Lead Vox"
    <ITEM
      NAME "take"
      <SOURCE WAVE
        FILE "audio/vox.wav"
      >
    >
    <FXCHAIN
      BYPASS 0 0 0
      <VST "VST: ReaEQ (Cockos)" reaeq.dll 0 "" 0
      >
    >
  >
  <TRACK
    NAME "Drum Bus"
    AUXRECV 0 0 1 0 0 0 0
  >
>
"""


def _types(graph):
    return {data["type"] for _, data in graph.nodes(data=True)}


def test_project_node_exists():
    graph = build_graph(parse_rpp(RPP))
    assert PROJECT_NODE_ID in graph
    assert graph.nodes[PROJECT_NODE_ID]["type"] == "project"


def test_track_nodes_exist():
    graph = build_graph(parse_rpp(RPP))
    track_nodes = [n for n, d in graph.nodes(data=True) if d["type"] == "track"]
    assert len(track_nodes) == 2


def test_media_item_and_audio_nodes_exist():
    graph = build_graph(parse_rpp(RPP))
    types = _types(graph)
    assert "media_item" in types
    assert "audio_file" in types


def test_fx_nodes_exist():
    graph = build_graph(parse_rpp(RPP))
    fx_nodes = [n for n, d in graph.nodes(data=True) if d["type"] == "fx"]
    assert len(fx_nodes) == 1
    assert graph.nodes[fx_nodes[0]]["family"] == "EQ"


def test_expected_edges_exist():
    graph = build_graph(parse_rpp(RPP))
    edge_types = {data["type"] for _, _, data in graph.edges(data=True)}
    assert "contains_track" in edge_types
    assert "contains_item" in edge_types
    assert "uses_audio_file" in edge_types
    assert "processes_with" in edge_types
    assert "sends_to" in edge_types


def test_graph_metadata_present():
    graph = build_graph(parse_rpp(RPP))
    meta = graph.graph
    assert meta["n_tracks"] == 2
    assert meta["n_fx"] == 1
    assert meta["n_media_items"] == 1
    assert "density" in meta


def test_unresolved_route_becomes_bus_node():
    rpp = """<REAPER_PROJECT 0.1 "x" 0
  <TRACK
    NAME "Bus"
    AUXRECV 42 0 1 0 0 0 0
  >
>
"""
    graph = build_graph(parse_rpp(rpp))
    bus_nodes = [n for n, d in graph.nodes(data=True) if d["type"] == "bus_or_target"]
    assert len(bus_nodes) == 1
    assert graph.graph["n_unresolved"] == 1
    unresolved = [
        (u, v, d)
        for u, v, d in graph.edges(data=True)
        if d["type"] == "has_unresolved_route"
    ]
    assert len(unresolved) == 1
    # Direction matches signal flow (phantom source -> receiving track) and the
    # edge carries the same per-send attributes as resolved sends_to edges.
    phantom, receiver, data = unresolved[0]
    assert phantom == bus_nodes[0]
    assert graph.nodes[receiver]["type"] == "track"
    assert data["send_mode"] == 0
    assert data["volume_db"] == 0.0


def test_graph_to_dict_roundtrips_structure():
    graph = build_graph(parse_rpp(RPP))
    payload = graph_to_dict(graph)
    assert {"nodes", "edges", "metadata"} <= set(payload)
    assert all("id" in node for node in payload["nodes"])
    assert all({"source", "target", "type"} <= set(edge) for edge in payload["edges"])
