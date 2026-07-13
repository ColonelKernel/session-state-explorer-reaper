"""``export_bundle()`` — one ``.rpp`` file in, one 5-file snapshot bundle out.

The bundle is the adapter's wire product (the analyzer never sees the nested
intermediate):

- ``adapter_descriptor.json`` — the bundle-level identity card.
- ``capabilities.json`` — the honest capability manifest (read pathway only).
- ``native.json`` — the complete native ``ProjectState`` dump (the
  losslessness guarantee; referenced by path+hash from the snapshot, never
  embedded in it).
- ``canonical.snapshot.json`` — the flat v0.2 ``CanonicalDAWSnapshot``.
- ``validation.json`` — the ``validate_snapshot`` report for the snapshot as
  written.

Determinism: ids are reset per export and ``snapshot_id`` is content-addressed
over the native model with the *containing* path normalised away, so the same
``.rpp`` content produces the same ``snapshot_id`` regardless of where the file
lives on disk or which machine ran the export. ``created_at`` defaults to the
source file's mtime (overridable via the ``created_at`` argument): it is the one
field that is not reproducible across a copy/checkout, since mtime is not
preserved by ``cp``/``git``; pass an explicit value when regenerating a fixture
that must be byte-identical.

Sanitization (on by default): home-directory prefixes in path strings —
POSIX (``/Users/<u>``, ``/home/<u>``) and Windows (``<drive>:\\Users\\<u>``) —
are replaced with ``"~"`` everywhere in the bundle, so a shared fixture never
leaks a user name. Only a real home *root* is redacted; a nested ``…/Users/…``
segment (e.g. a network mount) is left intact.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from os.path import basename
from pathlib import Path
from typing import Any, Optional

from canonical_snapshot import SourceInfo, flatten_session, validate_snapshot
from canonical_snapshot.ids import reset_id_counters

from .. import __version__ as ADAPTER_VERSION
from ..rpp_parser import parse_rpp
from .manifest import (
    CAPTURE_MODES,
    build_adapter_descriptor,
    build_capability_manifest,
)
from .mapper import to_canonical
from .native_models import ProjectState

BUNDLE_FILES = (
    "adapter_descriptor.json",
    "capabilities.json",
    "native.json",
    "canonical.snapshot.json",
    "validation.json",
)

# Any home-directory root — POSIX (``/Users/<u>``, ``/home/<u>``) or Windows
# (``<drive>:\Users\<u>``), any user, not just the current one — so a bundle
# sanitised on one machine leaks neither our nor a collaborator's user name.
# The leading negative lookbehind requires a path boundary before the root, so a
# nested segment like ``/mnt/backups/Users/carol`` (Users under another dir) is
# left intact instead of being corrupted.
_HOME_PREFIX_RE = re.compile(
    r"(?<![\w.\-:])([A-Za-z]:)?[\\/](?:Users|home)[\\/][^\\/\s\"']+",
    re.IGNORECASE,
)


def _redact_homes(value: str) -> str:
    # Current machine's actual home first (covers a non-standard $HOME), as a
    # prefix only so a mid-string occurrence can't be mangled.
    home = str(Path.home())
    if home not in ("/", "") and value.startswith(home):
        value = "~" + value[len(home):]
    return _HOME_PREFIX_RE.sub("~", value)


def _sanitize(obj: Any) -> Any:
    """Recursively redact home-directory prefixes in every string."""

    if isinstance(obj, str):
        return _redact_homes(obj)
    if isinstance(obj, dict):
        return {key: _sanitize(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(value) for value in obj]
    return obj


def _null_non_finite(obj: Any) -> Any:
    """Map non-finite floats (NaN/±Inf) to ``None`` so every bundle file is valid JSON."""

    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {key: _null_non_finite(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_null_non_finite(value) for value in obj]
    return obj


def _dump_json(payload: Any) -> bytes:
    # allow_nan=False is the backstop: a non-finite value the coercion misses fails the
    # export loudly rather than silently writing an RFC-8259-invalid NaN/Infinity token
    # into native.json / canonical.snapshot.json (and its content hash).
    body = json.dumps(
        _null_non_finite(payload), indent=2, ensure_ascii=False, allow_nan=False
    )
    return (body + "\n").encode("utf-8")


def _daw_version(header_platform: Optional[str]) -> Optional[str]:
    """Version part of the ``<REAPER_PROJECT`` header token (``"7.0/win64"`` -> ``"7.0"``)."""

    if not header_platform:
        return None
    return header_platform.split("/", 1)[0] or header_platform


def export_bundle(
    rpp_path: Path,
    out_dir: Path,
    *,
    audio_base: Optional[Path] = None,
    sanitize: bool = True,
    created_at: Optional[str] = None,
) -> dict[str, Any]:
    """Export one ``.rpp`` project as a canonical 5-file snapshot bundle.

    ``created_at`` defaults to the source file's mtime; pass an explicit ISO-8601
    string to make the bundle byte-reproducible (e.g. for fixture regeneration).

    Returns a small report: bundle file paths, the validation outcome, and
    entity/relationship counts. Raises :class:`FileNotFoundError` when
    ``rpp_path`` does not exist.
    """

    rpp_path = Path(rpp_path)
    if not rpp_path.is_file():
        raise FileNotFoundError(f"No such .rpp file: {rpp_path}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Deterministic ids for every export run.
    reset_id_counters()

    # -- parse: .rpp text -> native ProjectState ---------------------------
    text = rpp_path.read_text(encoding="utf-8", errors="replace")
    project = parse_rpp(text, source_file=str(rpp_path))

    # Sanitize ONCE at the source, before mapping: the contract derives some
    # entity ids by slugging path strings (e.g. asset ids from audio paths), so
    # redacting only the final JSON would still leak a user name inside those
    # ids. Sanitizing the project up front makes native.json, the canonical
    # entities, and every derived id consistent and clean.
    if sanitize:
        project = ProjectState.model_validate(_sanitize(project.model_dump()))

    # -- native.json (the losslessness artifact) ---------------------------
    native_dict = project.model_dump()
    native_bytes = _dump_json(native_dict)
    # native_sha256 is the integrity hash of native.json exactly as written.
    native_sha256 = hashlib.sha256(native_bytes).hexdigest()

    # snapshot_id is content-addressed but must be independent of *where* the
    # .rpp lives: normalise the top-level source_file (the path the CLI was
    # handed) to its basename so the same content at different absolute paths
    # (or on different machines) yields the same id.
    id_dict = dict(native_dict)
    if id_dict.get("source_file"):
        id_dict["source_file"] = basename(str(id_dict["source_file"]).replace("\\", "/"))
    content_sha256 = hashlib.sha256(_dump_json(id_dict)).hexdigest()

    # -- nested intermediate -> flat v0.2 snapshot --------------------------
    session = to_canonical(project, source_artifact="rpp_file")
    if audio_base is not None:
        session.metadata["audio_base_dir"] = str(audio_base)

    daw_version = _daw_version(project.header_platform)
    source = SourceInfo(
        daw="reaper",
        daw_version=daw_version,
        adapter="session-state-explorer-reaper",
        adapter_version=ADAPTER_VERSION,
        capture_modes=list(CAPTURE_MODES),
    )
    capabilities = build_capability_manifest(
        daw_version=daw_version, adapter_version=ADAPTER_VERSION
    )
    if created_at is None:
        created_at = datetime.fromtimestamp(
            rpp_path.stat().st_mtime, tz=timezone.utc
        ).isoformat()

    snapshot = flatten_session(
        session,
        source,
        capabilities,
        native_file="native.json",
        native_sha256=native_sha256,
        snapshot_id=f"reaper:rpp:{content_sha256[:16]}",
        created_at=created_at,
        default_stability="COMMUNITY_DOCUMENTED",
    )

    snapshot_dict = snapshot.model_dump()
    if sanitize:
        snapshot_dict = _sanitize(snapshot_dict)

    # -- validate exactly what will be written ------------------------------
    report = validate_snapshot(snapshot_dict)

    # -- write the 5-file bundle --------------------------------------------
    payloads = {
        "adapter_descriptor.json": build_adapter_descriptor().model_dump(),
        "capabilities.json": capabilities.model_dump(),
        "canonical.snapshot.json": snapshot_dict,
        "validation.json": report.model_dump(),
    }
    paths: dict[str, Path] = {}
    for name in BUNDLE_FILES:
        path = out_dir / name
        if name == "native.json":
            path.write_bytes(native_bytes)
        else:
            path.write_bytes(_dump_json(payloads[name]))
        paths[name] = path

    return {
        "bundle_dir": out_dir,
        "files": paths,
        "snapshot_id": snapshot_dict["snapshot_id"],
        "native_sha256": native_sha256,
        "valid": report.valid,
        "errors": list(report.errors),
        "warnings": list(report.warnings),
        "stats": dict(report.stats),
    }
