from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import hashlib
from typing import Any, Mapping, Optional, Tuple, Union

SCHEMA_VERSION = "1.0.0"


class EvidenceLevel(str, Enum):
    OFFICIAL_SUPPORTED = "official-supported"
    OFFICIAL_DOCUMENTED_VERSION_SENSITIVE = "official-documented-version-sensitive"
    LOCAL_IMPLEMENTATION_DETAIL = "local-implementation-detail"
    THIRD_PARTY_INFERENCE = "third-party-inference"
    UNCONFIRMED = "unconfirmed"


class SourceKind(str, Enum):
    CLAUDE_OTEL = "claude-otel"
    CLAUDE_HOOK = "claude-hook"
    CLAUDE_STATUSLINE = "claude-statusline"
    CLAUDE_SUBAGENT_STATUSLINE = "claude-subagent-statusline"
    CLAUDE_TRANSCRIPT_JSONL = "claude-transcript-jsonl"
    SYNTHETIC_FIXTURE = "synthetic-fixture"


class TimestampBasis(str, Enum):
    SOURCE_TIMESTAMP = "source-timestamp"
    COLLECTOR_OBSERVED_AT = "collector-observed-at"
    UNDATED = "undated"


class RoutingClassification(str, Enum):
    EXTERNALLY_REPORTED_MATCH = "externally_reported_match"
    ALIAS_RESOLUTION = "alias_resolution"
    CLIENT_SWITCH = "client_switch"
    DOCUMENTED_FALLBACK = "documented_fallback"
    OBSERVED_MODEL_MISMATCH = "observed_model_mismatch"
    SUBAGENT_SCOPE = "subagent_scope"
    COLLECTOR_GAP = "collector_gap"
    AMBIGUOUS = "ambiguous"
    UNVERIFIABLE_BACKEND_ROUTING = "unverifiable_backend_routing"


@dataclass(frozen=True, slots=True)
class VersionBoundary:
    min_inclusive: Optional[str] = None
    max_exclusive: Optional[str] = None


@dataclass(frozen=True, slots=True)
class FieldEvidence:
    level: EvidenceLevel
    source: SourceKind
    source_version: Optional[str] = None
    version_boundary: VersionBoundary = field(default_factory=VersionBoundary)
    note: Optional[str] = None


@dataclass(frozen=True, slots=True)
class CanonicalMetadata:
    source: SourceKind
    collected_at: datetime
    source_version: Optional[str] = None
    schema_version: str = SCHEMA_VERSION
    field_evidence: Mapping[str, FieldEvidence] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_aware(self.collected_at, "collected_at")


@dataclass(frozen=True, slots=True)
class RateLimitWindow:
    name: str
    used_percentage: Optional[float] = None
    resets_at: Optional[datetime] = None
    status: Optional[str] = None

    def __post_init__(self) -> None:
        if self.resets_at is not None:
            _require_aware(self.resets_at, "resets_at")
        if self.used_percentage is not None and not 0 <= self.used_percentage <= 100:
            raise ValueError("used_percentage must be between 0 and 100")


@dataclass(frozen=True, slots=True)
class UsageRecord:
    record_id: str
    timestamp: Optional[datetime]
    timestamp_basis: TimestampBasis
    session_id: Optional[str]
    prompt_id: Optional[str]
    request_id: Optional[str]
    message_id: Optional[str]
    agent_id: Optional[str]
    query_source: Optional[str]
    model_raw: Optional[str]
    model_resolved: Optional[str]
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_creation_5m_tokens: int = 0
    cache_creation_1h_tokens: int = 0
    reported_cost_usd: Optional[float] = None
    cost_basis: Optional[str] = None
    project_id: Optional[str] = None
    is_final: bool = False
    metadata: CanonicalMetadata = field(default_factory=lambda: _default_metadata(SourceKind.SYNTHETIC_FIXTURE))
    agent_name: Optional[str] = None

    def __post_init__(self) -> None:
        if self.timestamp is not None:
            _require_aware(self.timestamp, "timestamp")
        for name in ("input_tokens", "output_tokens", "cache_read_tokens", "cache_creation_tokens", "cache_creation_5m_tokens", "cache_creation_1h_tokens"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.reported_cost_usd is not None and self.reported_cost_usd < 0:
            raise ValueError("reported_cost_usd must be non-negative")

    @property
    def agent_scope(self) -> str:
        return self.agent_id or self.agent_name or "main"

    @property
    def dedupe_identity(self) -> Optional[Tuple[str, str, str, str]]:
        if not self.message_id and not self.request_id:
            return None
        return (self.session_id or "", self.message_id or "", self.request_id or "", self.agent_scope)


@dataclass(frozen=True, slots=True)
class MessageRecord:
    record_id: str
    timestamp: Optional[datetime]
    timestamp_basis: TimestampBasis
    session_id: Optional[str]
    prompt_id: Optional[str]
    turn_id: Optional[str]
    message_id: Optional[str]
    request_id: Optional[str]
    agent_id: Optional[str]
    role: str
    content_type: str
    content_length: int
    tool_name: Optional[str] = None
    tool_use_id: Optional[str] = None
    success: Optional[bool] = None
    project_id: Optional[str] = None
    metadata: CanonicalMetadata = field(default_factory=lambda: _default_metadata(SourceKind.SYNTHETIC_FIXTURE))

    def __post_init__(self) -> None:
        if self.timestamp is not None:
            _require_aware(self.timestamp, "timestamp")
        if self.content_length < 0:
            raise ValueError("content_length must be non-negative")


@dataclass(frozen=True, slots=True)
class SessionEvent:
    record_id: str
    timestamp: Optional[datetime]
    timestamp_basis: TimestampBasis
    session_id: Optional[str]
    prompt_id: Optional[str]
    event_type: str
    result_category: Optional[str]
    agent_id: Optional[str]
    project_id: Optional[str]
    tool_name: Optional[str] = None
    tool_use_id: Optional[str] = None
    interrupted: Optional[bool] = None
    metadata: CanonicalMetadata = field(default_factory=lambda: _default_metadata(SourceKind.SYNTHETIC_FIXTURE))

    def __post_init__(self) -> None:
        if self.timestamp is not None:
            _require_aware(self.timestamp, "timestamp")


@dataclass(frozen=True, slots=True)
class StatusSnapshot:
    record_id: str
    observed_at: datetime
    session_id: Optional[str]
    prompt_id: Optional[str]
    scope: str
    agent_id: Optional[str]
    model: Optional[str]
    repo_host: Optional[str]
    repo_owner: Optional[str]
    repo_name: Optional[str]
    pr_number: Optional[int]
    pr_url: Optional[str]
    pr_review_state: Optional[str]
    context_window_size: Optional[int]
    context_used_pct: Optional[float]
    rate_limit_windows: Tuple[RateLimitWindow, ...]
    permission_mode: Optional[str]
    agent_name: Optional[str]
    reported_session_cost_usd: Optional[float]
    collector_freshness_ms: Optional[int]
    metadata: CanonicalMetadata = field(default_factory=lambda: _default_metadata(SourceKind.SYNTHETIC_FIXTURE))

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        if self.context_window_size is not None and self.context_window_size < 0:
            raise ValueError("context_window_size must be non-negative")
        if self.context_used_pct is not None and not 0 <= self.context_used_pct <= 100:
            raise ValueError("context_used_pct must be between 0 and 100")
        if self.reported_session_cost_usd is not None and self.reported_session_cost_usd < 0:
            raise ValueError("reported_session_cost_usd must be non-negative")
        if self.collector_freshness_ms is not None and self.collector_freshness_ms < 0:
            raise ValueError("collector_freshness_ms must be non-negative")


@dataclass(frozen=True, slots=True)
class ModelIntentRecord:
    record_id: str
    observed_at: datetime
    session_id: Optional[str]
    prompt_id: Optional[str]
    agent_id: Optional[str]
    selected_model: Optional[str]
    requested_alias: Optional[str]
    client_resolved_model: Optional[str]
    config_scope: Optional[str]
    provider: Optional[str]
    switch_reason: Optional[str]
    metadata: CanonicalMetadata = field(default_factory=lambda: _default_metadata(SourceKind.SYNTHETIC_FIXTURE))
    request_id: Optional[str] = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class ModelObservationRecord:
    record_id: str
    observed_at: datetime
    session_id: Optional[str]
    prompt_id: Optional[str]
    request_id: Optional[str]
    message_id: Optional[str]
    agent_id: Optional[str]
    query_source: Optional[str]
    request_declared_model: Optional[str]
    response_reported_model: Optional[str]
    usage_reported_model: Optional[str]
    statusline_model: Optional[str]
    subagent_resolved_model: Optional[str]
    serving_model: Optional[str]
    speed: Optional[str]
    effort: Optional[str]
    attempt: Optional[int]
    fallback_reason: Optional[str]
    server_fallback_hop: Optional[bool]
    evidence_quality: EvidenceLevel
    metadata: CanonicalMetadata = field(default_factory=lambda: _default_metadata(SourceKind.SYNTHETIC_FIXTURE))
    agent_name: Optional[str] = None

    def __post_init__(self) -> None:
        _require_aware(self.observed_at, "observed_at")
        if self.attempt is not None and self.attempt < 0:
            raise ValueError("attempt must be non-negative")
        if self.serving_model is not None:
            raise ValueError("serving_model must remain unavailable without backend attestation")

    @property
    def agent_scope(self) -> str:
        return self.agent_id or self.agent_name or "main"


@dataclass(frozen=True, slots=True)
class RoutingAssessment:
    assessment_id: str
    session_id: Optional[str]
    prompt_id: Optional[str]
    request_id: Optional[str]
    agent_id: Optional[str]
    requested_model: Optional[str]
    resolved_model: Optional[str]
    reported_model: Optional[str]
    usage_model: Optional[str]
    serving_model: Optional[str]
    classification: RoutingClassification
    confidence: float
    evidence_sources: Tuple[SourceKind, ...]
    externally_reported_match: Optional[bool]
    backend_attestation_available: bool
    warnings: Tuple[str, ...] = ()
    agent_name: Optional[str] = None

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if self.backend_attestation_available:
            raise ValueError("backend_attestation_available must remain false")
        if self.serving_model is not None:
            raise ValueError("serving_model cannot be populated without backend attestation")


CanonicalRecord = Union[UsageRecord, MessageRecord, SessionEvent, StatusSnapshot, ModelIntentRecord, ModelObservationRecord, RoutingAssessment]


@dataclass(frozen=True, slots=True)
class CollectorBatch:
    records: Tuple[CanonicalRecord, ...]
    warnings: Tuple[str, ...] = ()


def stable_id(prefix: str, *parts: Any) -> str:
    normalized = "\x1f".join("" if part is None else str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(normalized.encode()).hexdigest()[:24]}"


def record_to_dict(record: CanonicalRecord) -> dict[str, Any]:
    return _jsonable(asdict(record))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _default_metadata(source: SourceKind) -> CanonicalMetadata:
    return CanonicalMetadata(source=source, collected_at=utc_now())


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


__all__ = ["SCHEMA_VERSION", "EvidenceLevel", "SourceKind", "TimestampBasis", "RoutingClassification", "VersionBoundary", "FieldEvidence", "CanonicalMetadata", "RateLimitWindow", "UsageRecord", "MessageRecord", "SessionEvent", "StatusSnapshot", "ModelIntentRecord", "ModelObservationRecord", "RoutingAssessment", "CollectorBatch", "CanonicalRecord", "stable_id", "record_to_dict", "utc_now"]
