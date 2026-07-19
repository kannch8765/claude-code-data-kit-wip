from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
import tarfile
from typing import Iterable, Iterator
import zipfile

from test_hygiene_rules import is_public_text_path, scan_named_texts


BOUNDARY_MARKERS = (
    "PWA" + "_TMUX",
    "pwa" + "-tmux",
    ".claude-" + "observability-lab",
    "claude-" + "observability-lab",
    "backend." + "observability",
)


@dataclass(frozen=True)
class AuditSummary:
    archive: str
    entries: int
    text_entries: int
    fixture_entries: int


def _zip_entries(path: Path) -> Iterator[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.endswith("/"):
                continue
            yield name, archive.read(name)


def _tar_entries(path: Path) -> Iterator[tuple[str, bytes]]:
    with tarfile.open(path, "r:gz") as archive:
        for member in archive.getmembers():
            if not member.isfile():
                continue
            handle = archive.extractfile(member)
            if handle is None:
                continue
            yield member.name, handle.read()


def _entries(path: Path) -> tuple[tuple[str, bytes], ...]:
    if path.suffix == ".whl":
        return tuple(_zip_entries(path))
    if path.name.endswith(".tar.gz"):
        return tuple(_tar_entries(path))
    raise ValueError(f"unsupported distribution: {path}")


def _text_entries(entries: Iterable[tuple[str, bytes]]) -> tuple[tuple[str, str], ...]:
    decoded: list[tuple[str, str]] = []
    for name, payload in entries:
        if not is_public_text_path(name):
            try:
                text = payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
        else:
            text = payload.decode("utf-8")
        decoded.append((name, text))
    return tuple(decoded)


def audit(path: Path) -> AuditSummary:
    entries = _entries(path)
    names = [name for name, _ in entries]
    text_entries = _text_entries(entries)
    findings = list(scan_named_texts(text_entries))

    for name, text in text_entries:
        for marker in BOUNDARY_MARKERS:
            if marker in text:
                findings.append(f"{name}: forbidden boundary marker: {marker}")

    archive_root_stripped = [
        PurePosixPath(*PurePosixPath(name).parts[1:]).as_posix()
        if path.name.endswith(".tar.gz") and len(PurePosixPath(name).parts) > 1
        else name
        for name in names
    ]
    if any(name.startswith("backend/") for name in archive_root_stripped):
        findings.append("backend package present")
    if any("tmux" in PurePosixPath(name).name.lower() for name in names):
        findings.append("tmux-named module or artifact present")
    if any(PurePosixPath(name).name.upper().startswith("LICENSE") for name in names):
        findings.append("license file present without maintainer decision")
    if any(
        PurePosixPath(name).suffix.lower() in {".env", ".key", ".pem", ".p12", ".pfx"}
        for name in names
    ):
        findings.append("private credential artifact extension present")

    fixture_entries = sum(
        "claude_code_data_kit/_fixtures/" in name for name in names
    )
    if fixture_entries < 5:
        findings.append("sanitized package fixture resources missing")

    if path.suffix == ".whl":
        metadata = next(
            text
            for name, text in text_entries
            if name.endswith(".dist-info/METADATA")
        )
        if "Requires-Dist:" in metadata:
            findings.append("runtime dependency metadata present")
        if not any(name.endswith(".dist-info/entry_points.txt") for name in names):
            findings.append("console entry point metadata missing")
    else:
        required_tests = (
            "tests/test_collectors.py",
            "tests/test_dedupe_routing.py",
            "tests/test_fixture_hygiene.py",
            "tests/test_goldens.py",
            "tests/test_hygiene_rules.py",
        )
        for required in required_tests:
            if not any(name.endswith(required) for name in names):
                findings.append(f"sdist missing contract test: {required}")

    if findings:
        raise AssertionError("\n".join(findings))
    return AuditSummary(
        archive=path.name,
        entries=len(entries),
        text_entries=len(text_entries),
        fixture_entries=fixture_entries,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archives", nargs="+")
    args = parser.parse_args(argv)
    for archive in args.archives:
        summary = audit(Path(archive))
        print(
            f"{summary.archive}: OK; entries={summary.entries}; "
            f"text_entries={summary.text_entries}; fixtures={summary.fixture_entries}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
