"""Canonical-export adapter: ``.rpp`` files in, v0.2 snapshot bundles out.

Relocated from the analyzer repo per the pivot plan ("four observation
instruments, one analysis contract"); origin ``SessionStateExplorer@041f529``,
``src/session_explorer/drivers/reaper/``. This repo is the REAPER observation
instrument; the analyzer consumes the serialized bundle this package emits.

Relocation notes (what moved, what deliberately did not):

- ``mapper.py`` — moved; imports rewired to :mod:`canonical_snapshot.nested`
  (the nested v0.1 intermediate) and :mod:`canonical_snapshot.ids`.
- ``native_models.py`` — a re-export shim over this repo's own
  :mod:`session_state_explorer.models`, which is byte-identical to the
  analyzer's copy. Adapter repo wins; no duplicate model definitions.
- ``exporter.py`` — new; the analyzer's ``driver.py`` (registry plumbing)
  became ``export_bundle()`` producing the 5-file bundle.
- analyzer ``rpp_parser.py`` / ``fx_knowledge.py`` — NOT copied: diffed against
  this repo's originals and found identical modulo import paths (no fixes to
  port); the repo originals are used directly.
- analyzer ``colors.py`` — NOT copied: ``decode_color`` already lives
  (identically) in this repo's ``utils.py``; ``swell_platform`` was promoted
  from a parser-private helper to ``utils.swell_platform``.
- analyzer ``keywords.py`` — NOT copied: it wrapped the analyzer's merged
  ``core.roles.DEFAULT_KEYWORDS`` tables with a knowledge hook; this repo's
  ``utils.classify_fx_family`` / ``utils.classify_track_role`` already perform
  knowledge-aware classification against the original REAPER taxonomy and pass
  the identical test suite.
- analyzer ``rules.py`` — NOT relocated: it was a port of this repo's own
  ``recommendations.py`` into the analyzer rule engine; recommendations remain
  a presentation concern of this repo's app, not part of the wire contract.
"""

from .exporter import export_bundle
from .manifest import build_adapter_descriptor, build_capability_manifest
from .mapper import to_canonical, to_native
from .native_models import (
    FxState,
    MediaItemState,
    ProjectState,
    RouteState,
    TrackState,
)

__all__ = [
    "FxState",
    "MediaItemState",
    "ProjectState",
    "RouteState",
    "TrackState",
    "build_adapter_descriptor",
    "build_capability_manifest",
    "export_bundle",
    "to_canonical",
    "to_native",
]
