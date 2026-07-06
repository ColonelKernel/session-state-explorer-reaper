"""``sse-reaper`` — the adapter's command-line entry point.

Deliberately dependency-light: stdlib ``argparse`` only, so the CLI works in
the minimal install.

Usage::

    sse-reaper export-canonical <project.rpp> --out <dir> [--audio-base DIR]
               [--no-sanitize]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .exporter import export_bundle


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sse-reaper",
        description=(
            "Session State Explorer (REAPER) — canonical-export adapter. "
            "Emits v0.2 snapshot bundles for the cross-DAW analyzer."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    export = sub.add_parser(
        "export-canonical",
        help="Export a .rpp project as a 5-file canonical snapshot bundle.",
    )
    export.add_argument("project", type=Path, help="Path to the .rpp project file.")
    export.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Output directory for the bundle (created if missing).",
    )
    export.add_argument(
        "--audio-base",
        type=Path,
        default=None,
        help="Base directory for resolving relative audio paths (recorded, not rewritten).",
    )
    export.add_argument(
        "--no-sanitize",
        action="store_true",
        help="Keep home-directory prefixes in path strings (default: redact to '~').",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    if args.command == "export-canonical":
        try:
            result = export_bundle(
                args.project,
                args.out,
                audio_base=args.audio_base,
                sanitize=not args.no_sanitize,
            )
        except FileNotFoundError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except OSError as exc:
            # e.g. --out is unwritable (PermissionError) or points at an
            # existing file (FileExistsError/NotADirectoryError).
            print(f"error: could not write bundle: {exc}", file=sys.stderr)
            return 2

        stats = result["stats"]
        print(f"bundle:      {result['bundle_dir']}")
        print(f"snapshot_id: {result['snapshot_id']}")
        print(f"valid:       {result['valid']}")
        print(
            "contents:    "
            f"{stats.get('entities', 0)} entities, "
            f"{stats.get('relationships', 0)} relationships, "
            f"{stats.get('provenance_records', 0)} provenance records"
        )
        for error in result["errors"]:
            print(f"error:   {error}", file=sys.stderr)
        for warning in result["warnings"]:
            print(f"warning: {warning}", file=sys.stderr)
        return 0 if result["valid"] else 1

    return 2  # unreachable: argparse enforces the subcommand


if __name__ == "__main__":
    raise SystemExit(main())
