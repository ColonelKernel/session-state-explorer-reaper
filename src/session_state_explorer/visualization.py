"""Interactive graph visualization.

PyVis is the preferred renderer (draggable, physics-based HTML). When PyVis is not
installed, the module falls back to a Plotly network figure, which is dependency-light
and CI-friendly. Both paths share one colour scheme and one legend so the visual
language is consistent regardless of backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import networkx as nx

try:  # pragma: no cover - environment dependent
    from pyvis.network import Network

    PYVIS_AVAILABLE = True
except Exception:  # pragma: no cover
    PYVIS_AVAILABLE = False

from .graph_builder import PROJECT_NODE_ID

# Shared visual language: node type -> (hex colour, pyvis shape).
NODE_STYLES: Dict[str, Dict[str, str]] = {
    "project": {"color": "#4c78a8", "shape": "star"},
    "track": {"color": "#54a24b", "shape": "dot"},
    "media_item": {"color": "#f58518", "shape": "square"},
    "audio_file": {"color": "#e45756", "shape": "triangle"},
    "fx": {"color": "#b279a2", "shape": "diamond"},
    "bus_or_target": {"color": "#9d755d", "shape": "hexagon"},
    "route": {"color": "#9d755d", "shape": "hexagon"},
    "unknown": {"color": "#888888", "shape": "dot"},
}

# Human-readable legend (label -> colour) used in the Streamlit sidebar/legend.
LEGEND: List[tuple] = [
    ("Project", NODE_STYLES["project"]["color"]),
    ("Track", NODE_STYLES["track"]["color"]),
    ("Media item", NODE_STYLES["media_item"]["color"]),
    ("Audio file", NODE_STYLES["audio_file"]["color"]),
    ("FX", NODE_STYLES["fx"]["color"]),
    ("Route / bus", NODE_STYLES["bus_or_target"]["color"]),
    ("Unresolved / uncertain", NODE_STYLES["bus_or_target"]["color"]),
]


@dataclass
class GraphFilters:
    """Display filters for the graph. ``only_track`` restricts to one track subtree."""

    show_media_items: bool = True
    show_audio_files: bool = True
    show_fx: bool = True
    show_routes: bool = True
    only_track: Optional[str] = None  # track node id, or None for "all tracks"


def filter_graph(graph: nx.DiGraph, filters: GraphFilters) -> nx.DiGraph:
    """Return a new graph with nodes/edges removed per the display filters."""

    keep_types = {"project", "track"}
    if filters.show_media_items:
        keep_types.add("media_item")
    if filters.show_audio_files:
        keep_types.add("audio_file")
    if filters.show_fx:
        keep_types.add("fx")
    if filters.show_routes:
        keep_types.update({"bus_or_target", "route"})

    subgraph = nx.DiGraph()
    subgraph.graph.update(graph.graph)

    # Restrict to a single track's subtree when requested.
    allowed_nodes = None
    if filters.only_track and filters.only_track in graph:
        allowed_nodes = {PROJECT_NODE_ID, filters.only_track}
        allowed_nodes.update(nx.descendants(graph, filters.only_track))
        # Include resolved send neighbours so routing context is not lost.
        allowed_nodes.update(graph.successors(filters.only_track))
        allowed_nodes.update(graph.predecessors(filters.only_track))

    for node_id, data in graph.nodes(data=True):
        if data.get("type") not in keep_types:
            continue
        if allowed_nodes is not None and node_id not in allowed_nodes:
            continue
        subgraph.add_node(node_id, **data)

    for source, target, data in graph.edges(data=True):
        if source in subgraph and target in subgraph:
            if not filters.show_routes and data.get("type") in {
                "sends_to",
                "has_unresolved_route",
            }:
                continue
            subgraph.add_edge(source, target, **data)

    return subgraph


def _node_tooltip(data: dict) -> str:
    keys = [
        "type",
        "role",
        "family",
        "fx_type",
        "enabled",
        "preset",
        "volume_db",
        "pan",
        "tempo",
        "source_type",
        "path",
        "length",
    ]
    lines = [f"{data.get('label', data.get('id'))}"]
    for key in keys:
        if key in data and data[key] is not None:
            lines.append(f"{key}: {data[key]}")
    return "\n".join(lines)


def render_pyvis_html(
    graph: nx.DiGraph,
    height: str = "640px",
    hierarchical: bool = False,
    direction: str = "LR",
) -> str:
    """Build draggable PyVis HTML for the (already filtered) graph.

    With ``hierarchical=True`` the graph is laid out as a left-to-right (or the given
    ``direction``) layered flow — sources on the left, master/returns on the right —
    which reads like signal flow instead of a force-directed cloud. Otherwise the
    physics (Barnes-Hut) layout is used.
    """

    if not PYVIS_AVAILABLE:  # pragma: no cover - guarded by caller
        raise RuntimeError("PyVis is not available.")

    net = Network(
        height=height,
        width="100%",
        directed=True,
        bgcolor="#ffffff",
        font_color="#222222",
        notebook=False,
        cdn_resources="in_line",
    )
    if hierarchical:
        net.set_options(
            """{
  "layout": {
    "hierarchical": {
      "enabled": true,
      "direction": "%s",
      "sortMethod": "directed",
      "levelSeparation": 200,
      "nodeSpacing": 90,
      "treeSpacing": 120
    }
  },
  "physics": { "enabled": false },
  "edges": { "smooth": { "type": "cubicBezier", "roundness": 0.5 } }
}"""
            % direction
        )
    else:
        net.barnes_hut(gravity=-12000, spring_length=120, spring_strength=0.02)

    for node_id, data in graph.nodes(data=True):
        node_type = data.get("type", "unknown")
        style = NODE_STYLES.get(node_type, NODE_STYLES["unknown"])
        color = style["color"]
        if node_type == "fx" and data.get("enabled") is False:
            color = "#cccccc"  # bypassed FX read as muted grey
        if node_type == "bus_or_target" and data.get("resolved") is False:
            color = "#d62728"  # unresolved targets stand out
        net.add_node(
            node_id,
            label=str(data.get("label", node_id)),
            title=_node_tooltip(data),
            color=color,
            shape=style["shape"],
            size=26 if node_type in {"project", "track"} else 16,
        )

    _send_modes = {0: "post-fader", 1: "pre-FX", 2: "post-FX", 3: "post-FX"}
    for source, target, data in graph.edges(data=True):
        edge_type = data.get("type", "")
        label = ""
        if edge_type == "sends_to":
            label = _send_modes.get(data.get("send_mode"), "send")
        net.add_edge(
            source,
            target,
            title=edge_type,
            label=label,
            arrows="to",
            color="#d62728" if edge_type == "has_unresolved_route" else "#bbbbbb",
        )

    try:
        return net.generate_html(notebook=False)
    except TypeError:  # pragma: no cover - older pyvis signatures
        return net.generate_html()


def render_plotly_figure(graph: nx.DiGraph):
    """Build a Plotly network figure as a dependency-light fallback."""

    import plotly.graph_objects as go

    if graph.number_of_nodes() == 0:
        return go.Figure()

    pos = nx.spring_layout(graph, seed=42, k=0.6)

    edge_x: List[Optional[float]] = []
    edge_y: List[Optional[float]] = []
    for source, target in graph.edges():
        x0, y0 = pos[source]
        x1, y1 = pos[target]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        line=dict(width=1, color="#cccccc"),
        hoverinfo="none",
        mode="lines",
    )

    traces = [edge_trace]
    # One scatter trace per node type so the Plotly legend doubles as our legend.
    by_type: Dict[str, Dict[str, list]] = {}
    for node_id, data in graph.nodes(data=True):
        node_type = data.get("type", "unknown")
        bucket = by_type.setdefault(node_type, {"x": [], "y": [], "text": [], "hover": []})
        x, y = pos[node_id]
        bucket["x"].append(x)
        bucket["y"].append(y)
        bucket["text"].append(str(data.get("label", node_id)))
        bucket["hover"].append(_node_tooltip(data).replace("\n", "<br>"))

    for node_type, bucket in by_type.items():
        style = NODE_STYLES.get(node_type, NODE_STYLES["unknown"])
        traces.append(
            go.Scatter(
                x=bucket["x"],
                y=bucket["y"],
                mode="markers+text",
                name=node_type,
                text=bucket["text"],
                textposition="top center",
                textfont=dict(size=9),
                hovertext=bucket["hover"],
                hoverinfo="text",
                marker=dict(size=16, color=style["color"], line=dict(width=1, color="#ffffff")),
            )
        )

    figure = go.Figure(data=traces)
    figure.update_layout(
        showlegend=True,
        hovermode="closest",
        margin=dict(l=10, r=10, t=10, b=10),
        xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        height=640,
    )
    return figure
