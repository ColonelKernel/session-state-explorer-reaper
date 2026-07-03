"""Construct an interpretable, directed DAW-state graph from a parsed project.

The graph is the central representation of this prototype. It makes the structure of
a session explicit and inspectable: the *contains* hierarchy (project -> track ->
item -> audio file), the *processes-with* relationship (track -> FX), and the
*routing* relationships between tracks (sends/buses), including the ones we could
only partially observe.

Node types:  project, track, media_item, audio_file, fx, route, bus_or_target
Edge types:  contains_track, contains_item, uses_audio_file, processes_with,
             routes_to, sends_to, has_unresolved_route
"""

from __future__ import annotations

from typing import Dict

import networkx as nx

from .models import ProjectState

PROJECT_NODE_ID = "project"


def build_graph(project: ProjectState) -> nx.DiGraph:
    """Build a :class:`networkx.DiGraph` from a :class:`ProjectState`."""

    graph = nx.DiGraph()

    graph.add_node(
        PROJECT_NODE_ID,
        id=PROJECT_NODE_ID,
        label=project.project_name or "Project",
        type="project",
        tempo=project.tempo,
        sample_rate=project.sample_rate,
        source_file=project.source_file,
    )

    audio_file_nodes: Dict[str, str] = {}  # normalised path -> node id
    unresolved_count = 0

    for track in project.tracks:
        track_node = track.id
        graph.add_node(
            track_node,
            id=track_node,
            label=track.name or f"Track {track.index + 1}",
            type="track",
            index=track.index,
            role=track.role,
            volume_db=track.volume_db,
            pan=track.pan,
            mute=track.mute,
            solo=track.solo,
            main_send=track.main_send,
            color=track.color,
            n_fx=len(track.fx),
            n_items=len(track.media_items),
        )
        graph.add_edge(PROJECT_NODE_ID, track_node, type="contains_track")

        # Media items and their audio files.
        for item in track.media_items:
            item_node = item.id
            graph.add_node(
                item_node,
                id=item_node,
                label=item.name or "Media item",
                type="media_item",
                position=item.position,
                length=item.length,
                source_type=item.source_type,
                source_file=item.source_file,
            )
            graph.add_edge(track_node, item_node, type="contains_item")

            if item.source_file:
                key = item.source_file.strip()
                if key not in audio_file_nodes:
                    audio_node = f"audio-{len(audio_file_nodes)}"
                    audio_file_nodes[key] = audio_node
                    graph.add_node(
                        audio_node,
                        id=audio_node,
                        label=_basename(key),
                        type="audio_file",
                        path=key,
                        source_type=item.source_type,
                    )
                graph.add_edge(
                    item_node, audio_file_nodes[key], type="uses_audio_file"
                )

        # FX chain.
        for fx in track.fx:
            fx_node = fx.id
            graph.add_node(
                fx_node,
                id=fx_node,
                label=fx.name,
                type="fx",
                index=fx.index,
                fx_type=fx.fx_type,
                family=fx.family,
                enabled=fx.enabled,
                offline=fx.offline,
                chain=fx.chain,
                preset=fx.preset,
            )
            graph.add_edge(track_node, fx_node, type="processes_with")

    # Routing.
    for route in project.routes:
        route_node = route.id
        if route.route_type == "unresolved" or route.source_track_id is None:
            unresolved_count += 1
            # The unresolved end of an AUXRECV is the *source*; the receiving
            # track is real. Point the phantom node at the anchor so edge
            # direction still matches signal flow.
            graph.add_node(
                route_node,
                id=route_node,
                label=route.source_name or "Unresolved send source",
                type="bus_or_target",
                resolved=False,
            )
            # Anchor on a real node; fall back to the project node if the parser's
            # anchor is somehow missing, so we never create a typeless phantom node.
            anchor = (
                route.target_track_id
                if route.target_track_id in graph
                else PROJECT_NODE_ID
            )
            graph.add_edge(
                route_node,
                anchor,
                type="has_unresolved_route",
                route_id=route.id,
                send_mode=route.send_mode,
                volume_db=route.volume_db,
                mute=route.mute,
            )
        else:
            # A resolved send is a direct edge between two track nodes.
            graph.add_edge(
                route.source_track_id,
                route.target_track_id,
                type="sends_to",
                route_id=route.id,
                route_node=route_node,
                send_mode=route.send_mode,
                volume_db=route.volume_db,
                mute=route.mute,
            )

    graph.graph.update(
        {
            "n_tracks": len(project.tracks),
            "n_media_items": len(project.media_items),
            "n_fx": len(project.fx),
            "n_routes": len(project.routes),
            "n_audio_files": len(audio_file_nodes),
            "n_unresolved": unresolved_count,
            "density": round(nx.density(graph), 4) if graph.number_of_nodes() > 1 else 0.0,
            "n_warnings": len(project.warnings),
        }
    )
    return graph


def graph_to_dict(graph: nx.DiGraph) -> dict:
    """Serialise a graph to plain dicts suitable for JSON export or visualization."""

    nodes = []
    for node_id, data in graph.nodes(data=True):
        node = {"id": node_id}
        node.update({k: v for k, v in data.items() if k != "id"})
        nodes.append(node)

    edges = []
    for source, target, data in graph.edges(data=True):
        edge = {"source": source, "target": target}
        edge.update(data)
        edges.append(edge)

    return {"nodes": nodes, "edges": edges, "metadata": dict(graph.graph)}


def _basename(path: str) -> str:
    from os.path import basename

    return basename(path.replace("\\", "/")) or path
