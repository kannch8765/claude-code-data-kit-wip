from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from ..records import (
    CanonicalMetadata,
    EvidenceLevel,
    FieldEvidence,
    SourceKind,
    TimestampBasis,
    VersionBoundary,
    utc_now,
)


def nested_get(payload: Mapping[str, Any], path: str, default: Any = None) -> Any:
    """Read nested or literal dotted keys without exposing this helper publicly."""

    current: Any = payload
    parts = path.split(".")
    for index, part in enumerate(parts):
        if not isinstance(current, Mapping):
            return default
        remaining = ".".join(parts[index:])
        if remaining in current:
            return current[remaining]
        if part not in current:
            return default
        current = current[part]
    return current


def first(payload: Mapping[str, Any], *paths: str, default: Any = None) -> Any:
    for path in paths:
        value = nested_get(payload, path, default=None)
        if value is not None:
            return value
    return default


def as_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_bool(value: Any, default: Optional[bool] = None) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10**16:
            number /= 1_000_000_000
        elif number > 10**13:
            number /= 1_000_000
        elif number > 10**10:
            number /= 1_000
        return datetime.fromtimestamp(number, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def timestamp_with_basis(
    value: Any,
    observed_at: Optional[datetime] = None,
) -> tuple[Optional[datetime], TimestampBasis]:
    parsed = parse_timestamp(value)
    if parsed is not None:
        return parsed, TimestampBasis.SOURCE_TIMESTAMP
    if observed_at is not None:
        return observed_at, TimestampBasis.COLLECTOR_OBSERVED_AT
    return None, TimestampBasis.UNDATED


def source_version_from_resource(payload: Mapping[str, Any]) -> Optional[str]:
    return first(
        payload,
        "resource.attributes.service.version",
        "resource.service.version",
        "service.version",
        "version",
    )


def make_metadata(
    source: SourceKind,
    *,
    source_version: Optional[str],
    collected_at: Optional[datetime] = None,
    field_evidence: Optional[Mapping[str, FieldEvidence]] = None,
    warnings: Iterable[str] = (),
) -> CanonicalMetadata:
    return CanonicalMetadata(
        source=source,
        source_version=source_version,
        collected_at=collected_at or utc_now(),
        field_evidence=dict(field_evidence or {}),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def official_evidence(
    source: SourceKind,
    source_version: Optional[str],
    *,
    min_version: Optional[str] = None,
    max_version: Optional[str] = None,
    version_sensitive: bool = False,
    note: Optional[str] = None,
) -> FieldEvidence:
    return FieldEvidence(
        level=(
            EvidenceLevel.OFFICIAL_DOCUMENTED_VERSION_SENSITIVE
            if version_sensitive
            else EvidenceLevel.OFFICIAL_SUPPORTED
        ),
        source=source,
        source_version=source_version,
        version_boundary=VersionBoundary(min_version, max_version),
        note=note,
    )


def local_evidence(
    source: SourceKind,
    source_version: Optional[str],
    *,
    min_version: Optional[str] = None,
    max_version: Optional[str] = None,
    note: Optional[str] = None,
) -> FieldEvidence:
    return FieldEvidence(
        level=EvidenceLevel.LOCAL_IMPLEMENTATION_DETAIL,
        source=source,
        source_version=source_version,
        version_boundary=VersionBoundary(min_version, max_version),
        note=note,
    )


def string(value: Any) -> Optional[str]:
    """Normalize optional scalar text for private collector use."""

    if value is None:
        return None
    text = str(value).strip()
    return text or None
