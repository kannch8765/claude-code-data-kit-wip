from ._version import __version__
from .dedupe import dedupe_usage
from .records import (
    SCHEMA_VERSION,
    CanonicalMetadata,
    CanonicalRecord,
    CollectorBatch,
    EvidenceLevel,
    FieldEvidence,
    MessageRecord,
    ModelIntentRecord,
    ModelObservationRecord,
    RateLimitWindow,
    RoutingAssessment,
    RoutingClassification,
    SessionEvent,
    SourceKind,
    StatusSnapshot,
    TimestampBasis,
    UsageRecord,
    VersionBoundary,
    record_to_dict,
    stable_id,
)
from .routing import DarioSeizer, RoutingAccumulator

# These convenience imports are part of the stable top-level API. Collector
# adapters and lab helpers remain namespaced to avoid expanding this surface.
__all__ = [
    "__version__",
    "SCHEMA_VERSION",
    "CanonicalMetadata",
    "CanonicalRecord",
    "CollectorBatch",
    "EvidenceLevel",
    "FieldEvidence",
    "MessageRecord",
    "ModelIntentRecord",
    "ModelObservationRecord",
    "RateLimitWindow",
    "RoutingAssessment",
    "RoutingClassification",
    "SessionEvent",
    "SourceKind",
    "StatusSnapshot",
    "TimestampBasis",
    "UsageRecord",
    "VersionBoundary",
    "record_to_dict",
    "stable_id",
    "dedupe_usage",
    "DarioSeizer",
    "RoutingAccumulator",
]
