"""Serialise the parsed session, graph, descriptors and recommendations to JSON.

The export schema is intentionally simple and self-describing so it can be shown in
the README and reused as a unit of analysis in future research (e.g. comparing many
sessions). All payloads are plain JSON-serialisable dicts.
"""

from __future__ import annotations

import json
import math
from typing import List, Optional

import networkx as nx

from . import SCHEMA_VERSION
from .fingerprint import compute_session_fingerprint
from .graph_builder import graph_to_dict
from .models import AudioDescriptorSet, ProjectState, Recommendation


def build_export(
    project: ProjectState,
    graph: nx.DiGraph,
    descriptors: Optional[List[AudioDescriptorSet]] = None,
    recommendations: Optional[List[Recommendation]] = None,
) -> dict:
    """Assemble the full export document.

    The export also embeds a structural ``fingerprint`` so two exported sessions can
    be compared directly without re-parsing.
    """

    descriptors = descriptors or []
    recommendations = recommendations or []
    graph_dict = graph_to_dict(graph)

    return {
        "schema_version": SCHEMA_VERSION,
        "project": project.model_dump(exclude={"warnings"}),
        "graph": {
            "nodes": graph_dict["nodes"],
            "edges": graph_dict["edges"],
            "metadata": graph_dict["metadata"],
        },
        "descriptors": [d.model_dump() for d in descriptors],
        "recommendations": [r.model_dump() for r in recommendations],
        "fingerprint": compute_session_fingerprint(project, descriptors),
        "warnings": list(project.warnings),
    }


def to_json_str(payload: dict, indent: int = 2) -> str:
    """Pretty JSON string with safe defaults for numpy / non-serialisable values.

    Non-finite floats (``NaN``/``Infinity``, e.g. a NaN loudness from a silent stem)
    are coerced to ``null`` so the export is always valid RFC-8259 JSON; ``null`` reads
    as an honest "unobserved" gap rather than a token strict parsers reject. ``allow_nan``
    is left off as a backstop, so anything the sanitiser misses fails loudly instead of
    silently writing an invalid document.
    """

    return json.dumps(
        _replace_non_finite(payload), indent=indent, allow_nan=False, default=_json_default
    )


def to_json_bytes(payload: dict, indent: int = 2) -> bytes:
    """UTF-8 encoded JSON, convenient for Streamlit download buttons."""

    return to_json_str(payload, indent=indent).encode("utf-8")


def graph_export(graph: nx.DiGraph) -> dict:
    """Graph-only export (nodes/edges/metadata)."""

    payload = graph_to_dict(graph)
    return {"schema_version": SCHEMA_VERSION, "graph": payload}


def descriptors_export(descriptors: List[AudioDescriptorSet]) -> dict:
    """Descriptors-only export."""

    return {
        "schema_version": SCHEMA_VERSION,
        "descriptors": [d.model_dump() for d in descriptors],
    }


def recommendations_export(recommendations: List[Recommendation]) -> dict:
    """Recommendations-only export."""

    return {
        "schema_version": SCHEMA_VERSION,
        "recommendations": [r.model_dump() for r in recommendations],
    }


def _replace_non_finite(obj):
    """Recursively map non-finite floats (NaN/±Inf) to ``None`` for valid-JSON output."""

    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {key: _replace_non_finite(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_replace_non_finite(value) for value in obj]
    return obj


def _json_default(obj):
    """Fallback serialiser for numpy scalars and other stragglers."""

    # numpy scalar types expose .item(); avoid importing numpy here.
    if hasattr(obj, "item") and callable(obj.item):
        try:
            return obj.item()
        except Exception:  # pragma: no cover - defensive
            pass
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    return str(obj)
