from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
from typing import Optional, Sequence

from .store import DATA_DIR_ENV, StoreError
from .transcript_ingest import IngestSummary, TranscriptIngestor

_SOURCE_VERSION_ENV = "CLAUDE_CODE_DATA_KIT_SOURCE_VERSION"
_CLAUDE_EXECUTABLE_ENV = "CLAUDE_CODE_DATA_KIT_CLAUDE_EXECUTABLE"
_VERSION_PATTERN = re.compile(r"(?<!\d)(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-code-data-kit")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser(
        "ingest-transcripts",
        help="incrementally ingest Claude Code transcript JSONL",
    )
    ingest.add_argument(
        "path",
        nargs="?",
        default=str(Path.home() / ".claude" / "projects"),
        help="transcript JSONL file or directory (default: ~/.claude/projects)",
    )
    ingest.add_argument(
        "--data-dir",
        help=f"store directory (or ${DATA_DIR_ENV})",
    )
    ingest.add_argument(
        "--source-version",
        help=(
            "Claude Code source version; defaults to "
            f"${_SOURCE_VERSION_ENV} or local `claude --version`"
        ),
    )
    ingest.add_argument(
        "--json",
        action="store_true",
        help="emit one machine-readable JSON summary",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command != "ingest-transcripts":
        parser.error("unknown command")

    try:
        source_version = _resolve_source_version(args.source_version)
        ingestor = TranscriptIngestor(
            source_version=source_version,
            data_dir=args.data_dir,
        )
        summary = ingestor.ingest(args.path)
    except (FileNotFoundError, ValueError) as exc:
        _emit_configuration_error(str(exc), as_json=args.json)
        return 2
    except StoreError as exc:
        _emit_store_error(str(exc), as_json=args.json)
        return 3
    except OSError as exc:
        _emit_store_error(
            f"io_error:{exc.errno or type(exc).__name__}",
            as_json=args.json,
        )
        return 3

    _emit_summary(summary, as_json=args.json)
    return 1 if summary.files_failed else 0


def _resolve_source_version(explicit: Optional[str]) -> str:
    if explicit:
        return explicit.strip()
    configured = os.environ.get(_SOURCE_VERSION_ENV)
    if configured:
        return configured.strip()

    executable = os.environ.get(_CLAUDE_EXECUTABLE_ENV, "claude")
    command = shlex.split(executable)
    if not command:
        raise ValueError("claude_executable_is_empty")
    try:
        completed = subprocess.run(
            [*command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(
            "source_version_unavailable; pass --source-version"
        ) from exc
    combined = f"{completed.stdout}\n{completed.stderr}"
    match = _VERSION_PATTERN.search(combined)
    if completed.returncode != 0 or match is None:
        raise ValueError("source_version_unavailable; pass --source-version")
    return match.group(1)


def _emit_summary(summary: IngestSummary, *, as_json: bool) -> None:
    payload = summary.to_dict()
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return
    ordered_keys = (
        "files_seen",
        "files_changed",
        "records_parsed",
        "records_appended",
        "records_skipped_as_duplicate",
        "files_failed",
        "store_path",
        "state_path",
    )
    parts = []
    for key in ordered_keys:
        value = payload[key]
        parts.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
    print(" ".join(parts))
    for error in summary.errors:
        detail = error.to_dict()
        print(
            "error=" + json.dumps(detail, ensure_ascii=False, sort_keys=True),
            file=sys.stderr,
        )


def _emit_configuration_error(message: str, *, as_json: bool) -> None:
    payload = {"error": "configuration_error", "reason": message}
    if as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(f"configuration_error: {message}", file=sys.stderr)


def _emit_store_error(message: str, *, as_json: bool) -> None:
    payload = {"error": "store_error", "reason": message}
    if as_json:
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        print(f"store_error: {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["build_parser", "main"]
