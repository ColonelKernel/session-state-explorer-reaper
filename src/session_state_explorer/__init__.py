"""Session State Explorer v0.

A research prototype that parses a REAPER ``.rpp`` project into an interpretable,
partially observable DAW-state graph, extracts simple audio descriptors, and
produces explainable heuristic recommendations.

This package is intentionally lightweight. The audio and visualization layers
degrade gracefully when their optional third-party libraries are unavailable, so
the core parsing and graph-construction pipeline always works.
"""

from __future__ import annotations

__version__ = "0.5.0"
# JSON export schema version (unchanged by the canonical-export adapter, which
# emits the separate canonical_snapshot v0.2 contract format).
SCHEMA_VERSION = "0.3.0"

__all__ = ["__version__", "SCHEMA_VERSION"]
