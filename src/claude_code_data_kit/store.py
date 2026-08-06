from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable, Mapping, MutableMapping, Optional

from .records import (
    CanonicalRecord,
    MessageRecord,
    ModelIntentRecord,
    ModelObservationRecord,
    RoutingAssessment,
    SCHEMA_VERSION,
    SessionEvent,
    StatusSnapshot,
    UsageRecord,
    record_to_dict,
)

DATA_DIR_ENV = "CLAUDE_CODE_DATA_KIT_DATA_DIR"
STATE_SCHEMA_VERSION = "1.0.0"


class StoreError(RuntimeError):
    """Base class for local-store failures."""


class StoreCorruptionError(StoreError):
    """Raised when an existing store cannot be read safely."""


class RecordConflictError(StoreError):
    """Raised when a record ID already exists with different canonical data."""


@dataclass(frozen=True, slots=True)
class AppendResult:
    appended: int
    skipped_as_duplicate: int


def resolve_data_dir(
    override: Optional[os.PathLike[str] | str] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Path:
    """Resolve the product data directory without creating it."""

    env = os.environ if environ is None else environ
    if override is not None:
        return Path(override).expanduser()
    configured = env.get(DATA_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    xdg_home = env.get("XDG_DATA_HOME")
    if xdg_home:
        return Path(xdg_home).expanduser() / "claude-code-data-kit"
    return Path.home() / ".local" / "share" / "claude-code-data-kit"


class CanonicalRecordStore:
    """Append-only JSONL store with record-ID replay protection."""

    def __init__(self, data_dir: os.PathLike[str] | str) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "records.jsonl"
        _ensure_private_directory(self.data_dir)
        self._records_by_id: dict[str, bytes] = {}
        self._load_index_and_repair_partial_tail()

    def append(self, records: Iterable[CanonicalRecord]) -> AppendResult:
        pending: list[tuple[str, bytes]] = []
        pending_by_id: dict[str, bytes] = {}
        skipped = 0

        for record in records:
            envelope = canonical_record_envelope(record)
            record_id = envelope["record_id"]
            encoded = _stable_json_bytes(envelope) + b"\n"

            if record_id in self._records_by_id:
                # Canonical record IDs are the replay identity. Observation-time
                # fields can legitimately differ when a records append is
                # replayed after the state cursor failed to commit.
                skipped += 1
                continue

            if record_id in pending_by_id:
                skipped += 1
                continue

            pending.append((record_id, encoded))
            pending_by_id[record_id] = encoded

        if pending:
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            fd = os.open(self.path, flags, 0o600)
            try:
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
                payload = b"".join(encoded for _, encoded in pending)
                _write_all(fd, payload)
                os.fsync(fd)
            finally:
                os.close(fd)
            self._records_by_id.update(pending)

        return AppendResult(
            appended=len(pending),
            skipped_as_duplicate=skipped,
        )

    def _load_index_and_repair_partial_tail(self) -> None:
        if not self.path.exists():
            return
        if not self.path.is_file():
            raise StoreCorruptionError("records_path_is_not_a_file")

        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass
        with self.path.open("r+b") as handle:
            while True:
                line_start = handle.tell()
                line = handle.readline()
                if not line:
                    break
                if not line.endswith(b"\n"):
                    handle.truncate(line_start)
                    handle.flush()
                    os.fsync(handle.fileno())
                    break
                try:
                    payload = json.loads(line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise StoreCorruptionError(
                        f"invalid_records_jsonl_at_byte:{line_start}"
                    ) from exc
                if not isinstance(payload, MutableMapping):
                    raise StoreCorruptionError(
                        f"non_object_record_at_byte:{line_start}"
                    )
                record_id = payload.get("record_id")
                if not isinstance(record_id, str) or not record_id:
                    raise StoreCorruptionError(
                        f"missing_record_id_at_byte:{line_start}"
                    )
                stable_line = _stable_json_bytes(payload) + b"\n"
                self._records_by_id.setdefault(record_id, stable_line)


class StateStore:
    """Small atomically replaced JSON state file."""

    def __init__(self, data_dir: os.PathLike[str] | str) -> None:
        self.data_dir = Path(data_dir)
        self.path = self.data_dir / "state.json"
        _ensure_private_directory(self.data_dir)

    def load(self) -> dict[str, object]:
        if not self.path.exists():
            return {
                "schema_version": STATE_SCHEMA_VERSION,
                "sources": {},
                "last_successful_ingest_at": None,
            }
        if not self.path.is_file():
            raise StoreCorruptionError("state_path_is_not_a_file")
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoreCorruptionError("invalid_state_json") from exc
        if not isinstance(payload, dict):
            raise StoreCorruptionError("state_must_be_an_object")
        if payload.get("schema_version") != STATE_SCHEMA_VERSION:
            raise StoreCorruptionError("unsupported_state_schema_version")
        sources = payload.get("sources")
        if not isinstance(sources, dict):
            raise StoreCorruptionError("state_sources_must_be_an_object")
        return payload

    def save(self, state: Mapping[str, object]) -> None:
        payload = dict(state)
        payload["schema_version"] = STATE_SCHEMA_VERSION
        encoded = _stable_json_bytes(payload) + b"\n"
        _atomic_write(self.path, encoded)


def canonical_record_envelope(record: CanonicalRecord) -> dict[str, object]:
    record_id = getattr(record, "record_id", None)
    if record_id is None and isinstance(record, RoutingAssessment):
        record_id = record.assessment_id
    if not isinstance(record_id, str) or not record_id:
        raise StoreError("canonical_record_missing_id")
    payload = record_to_dict(record)
    payload["kind"] = _record_kind(record)
    payload["schema_version"] = SCHEMA_VERSION
    payload["record_id"] = record_id
    return payload


def _record_kind(record: CanonicalRecord) -> str:
    if isinstance(record, UsageRecord):
        return "usage"
    if isinstance(record, MessageRecord):
        return "message"
    if isinstance(record, SessionEvent):
        return "session_event"
    if isinstance(record, StatusSnapshot):
        return "status_snapshot"
    if isinstance(record, ModelIntentRecord):
        return "model_intent"
    if isinstance(record, ModelObservationRecord):
        return "model_observation"
    if isinstance(record, RoutingAssessment):
        return "routing_assessment"
    raise StoreError(f"unsupported_canonical_record:{type(record).__name__}")


def _stable_json_bytes(value: object) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise StoreError("canonical_json_encoding_failed") from exc
    return text.encode("utf-8")


def _ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_dir():
        raise StoreError("data_path_is_not_a_directory")
    try:
        os.chmod(path, 0o700)
    except OSError:
        # Some filesystems do not expose POSIX mode bits. Creation and atomicity
        # still work there, so mode tightening remains best-effort.
        pass


def _atomic_write(path: Path, payload: bytes) -> None:
    _ensure_private_directory(path.parent)
    temporary_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.chmod(temporary_path, 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        _fsync_directory(path.parent)
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def _write_all(fd: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise StoreError("records_append_made_no_progress")
        view = view[written:]


def _fsync_directory(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


__all__ = [
    "AppendResult",
    "CanonicalRecordStore",
    "DATA_DIR_ENV",
    "RecordConflictError",
    "STATE_SCHEMA_VERSION",
    "StateStore",
    "StoreCorruptionError",
    "StoreError",
    "canonical_record_envelope",
    "resolve_data_dir",
]
