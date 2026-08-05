from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Callable, Iterable, Mapping, MutableMapping, Optional

from .collectors.transcript import ClaudeTranscriptAdapter
from .records import CanonicalRecord, VersionBoundary
from .store import CanonicalRecordStore, StateStore, StoreCorruptionError, resolve_data_dir
from .versioning import version_allows

_TRANSCRIPT_BOUNDARY = VersionBoundary(min_inclusive="2.0.0", max_exclusive="3.0.0")
_CHECKPOINT_BYTES = 4096
_BATCH_LINES = 256


@dataclass(frozen=True, slots=True)
class IngestError:
    path: str
    reason: str
    byte_offset: Optional[int] = None
    line_number: Optional[int] = None

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {"path": self.path, "reason": self.reason}
        if self.byte_offset is not None:
            payload["byte_offset"] = self.byte_offset
        if self.line_number is not None:
            payload["line_number"] = self.line_number
        return payload


@dataclass(slots=True)
class IngestSummary:
    files_seen: int = 0
    files_changed: int = 0
    records_parsed: int = 0
    records_appended: int = 0
    records_skipped_as_duplicate: int = 0
    files_failed: int = 0
    store_path: str = ""
    state_path: str = ""
    errors: list[IngestError] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "files_seen": self.files_seen,
            "files_changed": self.files_changed,
            "records_parsed": self.records_parsed,
            "records_appended": self.records_appended,
            "records_skipped_as_duplicate": self.records_skipped_as_duplicate,
            "files_failed": self.files_failed,
            "store_path": self.store_path,
            "state_path": self.state_path,
            "errors": [error.to_dict() for error in self.errors],
        }


class TranscriptIngestor:
    """Incrementally ingest complete transcript JSONL lines into a local store."""

    def __init__(
        self,
        *,
        source_version: str,
        data_dir: os.PathLike[str] | str | None = None,
        adapter: Optional[ClaudeTranscriptAdapter] = None,
        after_records_append: Optional[Callable[[], None]] = None,
    ) -> None:
        if not version_allows(source_version, _TRANSCRIPT_BOUNDARY):
            raise ValueError("unsupported_or_unknown_transcript_version")
        self.source_version = source_version
        self.data_dir = resolve_data_dir(data_dir)
        self.records = CanonicalRecordStore(self.data_dir)
        self.state_store = StateStore(self.data_dir)
        self.adapter = adapter or ClaudeTranscriptAdapter()
        self._after_records_append = after_records_append

    def ingest(self, source_path: os.PathLike[str] | str) -> IngestSummary:
        source = Path(source_path).expanduser()
        candidates = discover_transcript_files(source, excluded={self.records.path})
        summary = IngestSummary(
            files_seen=len(candidates),
            store_path=str(self.records.path),
            state_path=str(self.state_store.path),
        )
        state = self.state_store.load()
        sources = state.get("sources")
        if not isinstance(sources, MutableMapping):
            raise StoreCorruptionError("state_sources_must_be_an_object")

        seen_physical_sources: set[str] = set()
        for path in candidates:
            try:
                with path.open("rb") as handle:
                    stat_result = os.fstat(handle.fileno())
                    source_id = _source_id(stat_result)
                    if source_id in seen_physical_sources:
                        continue
                    seen_physical_sources.add(source_id)
                    self._ingest_open_file(
                        path=path,
                        handle=handle,
                        stat_result=stat_result,
                        source_id=source_id,
                        state=state,
                        sources=sources,
                        summary=summary,
                    )
            except OSError as exc:
                summary.files_failed += 1
                summary.errors.append(
                    IngestError(
                        path=str(path),
                        reason=f"io_error:{exc.errno or type(exc).__name__}",
                    )
                )
        return summary

    def _ingest_open_file(
        self,
        *,
        path: Path,
        handle,
        stat_result: os.stat_result,
        source_id: str,
        state: MutableMapping[str, object],
        sources: MutableMapping[str, object],
        summary: IngestSummary,
    ) -> None:
        absolute_path = str(path.resolve())
        existing = sources.get(source_id)
        entry = _validated_source_entry(existing) if existing is not None else None
        reset = False

        if entry is None:
            entry = _new_source_entry(
                source_id=source_id,
                path=absolute_path,
                stat_result=stat_result,
            )
            reset = True
        else:
            offset = int(entry["offset"])
            if offset > stat_result.st_size or not _checkpoint_matches(
                handle, entry, offset
            ):
                entry = _new_source_entry(
                    source_id=source_id,
                    path=absolute_path,
                    stat_result=stat_result,
                    generation=int(entry.get("generation", 0)) + 1,
                )
                reset = True
            else:
                entry["path"] = absolute_path

        start_offset = int(entry["offset"])
        changed = reset or stat_result.st_size > start_offset
        if changed:
            summary.files_changed += 1

        # Persist source identity and any reset before parsing. This keeps the
        # generation stable even when the first new line is malformed.
        if reset or existing is None or existing.get("path") != absolute_path:
            sources[source_id] = entry
            self.state_store.save(state)

        handle.seek(start_offset)
        committed_offset = start_offset
        committed_line_number = int(entry.get("line_number", 0))
        batch_records: list[CanonicalRecord] = []
        batch_end_offset = committed_offset
        batch_line_number = committed_line_number
        batch_line_count = 0

        while True:
            line_start = handle.tell()
            raw_line = handle.readline()
            if not raw_line:
                break
            line_end = handle.tell()
            if not raw_line.endswith(b"\n"):
                # A writer may still be completing this line. It remains fully
                # replayable because the cursor stays before it.
                break

            logical_line_number = batch_line_number + 1
            line_payload = raw_line[:-1]
            if line_payload.endswith(b"\r"):
                line_payload = line_payload[:-1]

            try:
                decoded = line_payload.decode("utf-8")
            except UnicodeDecodeError:
                self._flush_batch(
                    handle=handle,
                    source_id=source_id,
                    entry=entry,
                    state=state,
                    sources=sources,
                    records=batch_records,
                    end_offset=batch_end_offset,
                    line_number=batch_line_number,
                    summary=summary,
                )
                _record_file_error(
                    summary,
                    path,
                    "invalid_utf8",
                    line_start,
                    logical_line_number,
                )
                return

            if not decoded.strip():
                records: tuple[CanonicalRecord, ...] = ()
            else:
                try:
                    payload = json.loads(decoded)
                except json.JSONDecodeError:
                    self._flush_batch(
                        handle=handle,
                        source_id=source_id,
                        entry=entry,
                        state=state,
                        sources=sources,
                        records=batch_records,
                        end_offset=batch_end_offset,
                        line_number=batch_line_number,
                        summary=summary,
                    )
                    _record_file_error(
                        summary,
                        path,
                        "malformed_json",
                        line_start,
                        logical_line_number,
                    )
                    return
                if not isinstance(payload, Mapping):
                    self._flush_batch(
                        handle=handle,
                        source_id=source_id,
                        entry=entry,
                        state=state,
                        sources=sources,
                        records=batch_records,
                        end_offset=batch_end_offset,
                        line_number=batch_line_number,
                        summary=summary,
                    )
                    _record_file_error(
                        summary,
                        path,
                        "non_object_json",
                        line_start,
                        logical_line_number,
                    )
                    return
                position = _position_number(
                    source_id,
                    int(entry.get("generation", 0)),
                    line_start,
                )
                try:
                    parsed = self.adapter.parse_record(
                        payload,
                        source_version=self.source_version,
                        line_number=position,
                    )
                except Exception as exc:
                    self._flush_batch(
                        handle=handle,
                        source_id=source_id,
                        entry=entry,
                        state=state,
                        sources=sources,
                        records=batch_records,
                        end_offset=batch_end_offset,
                        line_number=batch_line_number,
                        summary=summary,
                    )
                    _record_file_error(
                        summary,
                        path,
                        f"adapter_error:{type(exc).__name__}",
                        line_start,
                        logical_line_number,
                    )
                    return
                records = parsed.records

            summary.records_parsed += len(records)
            batch_records.extend(records)
            batch_end_offset = line_end
            batch_line_number = logical_line_number
            batch_line_count += 1

            if batch_line_count >= _BATCH_LINES:
                self._flush_batch(
                    handle=handle,
                    source_id=source_id,
                    entry=entry,
                    state=state,
                    sources=sources,
                    records=batch_records,
                    end_offset=batch_end_offset,
                    line_number=batch_line_number,
                    summary=summary,
                )
                committed_offset = batch_end_offset
                committed_line_number = batch_line_number
                batch_records = []
                batch_line_count = 0

        self._flush_batch(
            handle=handle,
            source_id=source_id,
            entry=entry,
            state=state,
            sources=sources,
            records=batch_records,
            end_offset=batch_end_offset,
            line_number=batch_line_number,
            summary=summary,
        )

    def _flush_batch(
        self,
        *,
        handle,
        source_id: str,
        entry: MutableMapping[str, object],
        state: MutableMapping[str, object],
        sources: MutableMapping[str, object],
        records: Iterable[CanonicalRecord],
        end_offset: int,
        line_number: int,
        summary: IngestSummary,
    ) -> None:
        current_offset = int(entry.get("offset", 0))
        if end_offset == current_offset:
            return
        append_result = self.records.append(records)
        summary.records_appended += append_result.appended
        summary.records_skipped_as_duplicate += append_result.skipped_as_duplicate
        if append_result.appended and self._after_records_append is not None:
            self._after_records_append()

        stat_result = os.fstat(handle.fileno())
        entry["offset"] = end_offset
        entry["line_number"] = line_number
        entry["file_size"] = stat_result.st_size
        entry["mtime_ns"] = stat_result.st_mtime_ns
        entry["prefix_fingerprint"] = _fingerprint(
            handle, 0, min(end_offset, _CHECKPOINT_BYTES)
        )
        tail_start = max(0, end_offset - _CHECKPOINT_BYTES)
        entry["tail_fingerprint"] = _fingerprint(
            handle, tail_start, end_offset - tail_start
        )
        entry["updated_at"] = _utc_now_text()
        sources[source_id] = entry
        _update_state_timestamp(state)
        self.state_store.save(state)


def discover_transcript_files(
    source: Path,
    *,
    excluded: Iterable[Path] = (),
) -> list[Path]:
    excluded_resolved = {path.resolve() for path in excluded}
    if not source.exists():
        raise FileNotFoundError(str(source))
    if source.is_symlink():
        raise ValueError("symlink_transcript_paths_are_not_supported")
    if source.is_file():
        if source.suffix.lower() != ".jsonl":
            raise ValueError("transcript_file_must_end_in_jsonl")
        resolved = source.resolve()
        return [] if resolved in excluded_resolved else [source]
    if not source.is_dir():
        raise ValueError("transcript_path_must_be_a_file_or_directory")

    candidates: list[Path] = []
    for root, directories, files in os.walk(source, followlinks=False):
        directories[:] = sorted(
            name
            for name in directories
            if not (Path(root) / name).is_symlink()
        )
        for filename in sorted(files):
            if not filename.lower().endswith(".jsonl"):
                continue
            path = Path(root) / filename
            if path.is_symlink() or not path.is_file():
                continue
            if path.resolve() in excluded_resolved:
                continue
            candidates.append(path)
    return sorted(candidates, key=lambda path: str(path))


def _source_id(stat_result: os.stat_result) -> str:
    identity = f"{stat_result.st_dev}:{stat_result.st_ino}"
    return "source_" + hashlib.sha256(identity.encode("ascii")).hexdigest()[:24]


def _new_source_entry(
    *,
    source_id: str,
    path: str,
    stat_result: os.stat_result,
    generation: int = 0,
) -> dict[str, object]:
    empty_hash = hashlib.sha256(b"").hexdigest()
    return {
        "source_id": source_id,
        "device": stat_result.st_dev,
        "inode": stat_result.st_ino,
        "generation": generation,
        "path": path,
        "offset": 0,
        "line_number": 0,
        "file_size": stat_result.st_size,
        "mtime_ns": stat_result.st_mtime_ns,
        "prefix_fingerprint": {"start": 0, "length": 0, "sha256": empty_hash},
        "tail_fingerprint": {"start": 0, "length": 0, "sha256": empty_hash},
        "updated_at": _utc_now_text(),
    }


def _validated_source_entry(value: object) -> MutableMapping[str, object]:
    if not isinstance(value, MutableMapping):
        raise StoreCorruptionError("invalid_source_state")
    required = {
        "source_id",
        "device",
        "inode",
        "generation",
        "path",
        "offset",
        "line_number",
        "prefix_fingerprint",
        "tail_fingerprint",
    }
    if not required.issubset(value):
        raise StoreCorruptionError("invalid_source_state")
    try:
        offset = int(value["offset"])
        line_number = int(value["line_number"])
    except (TypeError, ValueError) as exc:
        raise StoreCorruptionError("invalid_source_state") from exc
    if offset < 0 or line_number < 0:
        raise StoreCorruptionError("invalid_source_state")
    return dict(value)


def _checkpoint_matches(handle, entry: Mapping[str, object], offset: int) -> bool:
    if offset == 0:
        return True
    for key in ("prefix_fingerprint", "tail_fingerprint"):
        fingerprint = entry.get(key)
        if not isinstance(fingerprint, Mapping):
            return False
        try:
            start = int(fingerprint["start"])
            length = int(fingerprint["length"])
            expected = str(fingerprint["sha256"])
        except (KeyError, TypeError, ValueError):
            return False
        if start < 0 or length < 0 or start + length > offset:
            return False
        actual = _fingerprint(handle, start, length)
        if actual["sha256"] != expected:
            return False
    return True


def _fingerprint(handle, start: int, length: int) -> dict[str, object]:
    previous = handle.tell()
    try:
        handle.seek(start)
        payload = handle.read(length)
    finally:
        handle.seek(previous)
    if len(payload) != length:
        return {"start": start, "length": len(payload), "sha256": ""}
    return {
        "start": start,
        "length": length,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _position_number(source_id: str, generation: int, byte_offset: int) -> int:
    payload = f"{source_id}:{generation}:{byte_offset}".encode("ascii")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big")


def _record_file_error(
    summary: IngestSummary,
    path: Path,
    reason: str,
    byte_offset: int,
    line_number: int,
) -> None:
    summary.files_failed += 1
    summary.errors.append(
        IngestError(
            path=str(path),
            reason=reason,
            byte_offset=byte_offset,
            line_number=line_number,
        )
    )


def _update_state_timestamp(state: MutableMapping[str, object]) -> None:
    state["last_successful_ingest_at"] = _utc_now_text()


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = [
    "IngestError",
    "IngestSummary",
    "TranscriptIngestor",
    "discover_transcript_files",
]
