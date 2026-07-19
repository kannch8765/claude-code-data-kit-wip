from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
from typing import Optional, Sequence

from .lab import ClaudeLabRunner, ClaudeLabSpec, synthetic_check


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="claude-code-data-kit-lab")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--version", required=True, dest="claude_version")
    parser.add_argument(
        "--allow-network",
        action="store_true",
        help="Explicitly allow a network-requiring command.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare")
    install = subparsers.add_parser("install")
    install.add_argument("--allow-network", action="store_true", dest="command_network")
    subparsers.add_parser("version")
    subparsers.add_parser("help")
    probe = subparsers.add_parser("unauthenticated-probe")
    probe.add_argument("--allow-network", action="store_true", dest="command_network")
    subparsers.add_parser("synthetic-check")
    return parser


def _emit(payload: object) -> None:
    print(json.dumps(payload, sort_keys=True))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    spec = ClaudeLabSpec(args.root, args.claude_version)
    runner = ClaudeLabRunner(spec)
    allow_network = bool(
        args.allow_network or getattr(args, "command_network", False)
    )
    try:
        if args.command == "prepare":
            spec.prepare()
            _emit(
                {
                    "command": "prepare",
                    "managed": True,
                    "version": spec.claude_version,
                }
            )
            return 0
        if args.command == "install":
            result = runner.install(allow_network=allow_network)
        elif args.command == "version":
            result = runner.run(spec.version_command())
        elif args.command == "help":
            result = runner.run(spec.help_command())
        elif args.command == "unauthenticated-probe":
            result = runner.probe_unauthenticated_error_path(
                allow_network=allow_network
            )
        elif args.command == "synthetic-check":
            _emit(synthetic_check(spec))
            return 0
        else:  # pragma: no cover - argparse enforces the choices.
            parser.error(f"unsupported command: {args.command}")
            return 2
    except (PermissionError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _emit(asdict(result))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
