from __future__ import annotations
from dataclasses import replace
from datetime import datetime, timezone
import json
from typing import Dict, Iterable, Tuple
from .records import CanonicalMetadata, UsageRecord, record_to_dict

def dedupe_usage(records: Iterable[UsageRecord]) -> tuple[UsageRecord, ...]:
    keyed: Dict[Tuple[str, str, str, str], UsageRecord] = {}
    unkeyed: list[UsageRecord] = []
    for record in records:
        identity = record.dedupe_identity
        if identity is None:
            unkeyed.append(record)
        else:
            keyed[identity] = record if identity not in keyed else _merge(keyed[identity], record)
    combined = list(keyed.values()) + unkeyed
    combined.sort(key=_sort_key)
    return tuple(combined)

def _merge(left: UsageRecord, right: UsageRecord) -> UsageRecord:
    preferred, other = _preferred(left, right)
    warnings = list(preferred.metadata.warnings)
    if len({v for v in (left.model_resolved, right.model_resolved, left.model_raw, right.model_raw) if v}) > 1:
        warnings.append("conflicting_model_labels_for_same_usage_identity")
    if left.reported_cost_usd is not None and right.reported_cost_usd is not None and left.reported_cost_usd != right.reported_cost_usd:
        warnings.append("conflicting_cost_for_same_usage_identity")
    evidence = dict(other.metadata.field_evidence); evidence.update(preferred.metadata.field_evidence)
    metadata = CanonicalMetadata(source=preferred.metadata.source, source_version=preferred.metadata.source_version or other.metadata.source_version, collected_at=max(preferred.metadata.collected_at, other.metadata.collected_at), schema_version=preferred.metadata.schema_version, field_evidence=evidence, warnings=tuple(dict.fromkeys(warnings + list(other.metadata.warnings))))
    return replace(preferred, timestamp=_latest(left.timestamp, right.timestamp), prompt_id=preferred.prompt_id or other.prompt_id, query_source=preferred.query_source or other.query_source, model_raw=preferred.model_raw or other.model_raw, model_resolved=preferred.model_resolved or other.model_resolved, agent_name=preferred.agent_name or other.agent_name, input_tokens=max(left.input_tokens, right.input_tokens), output_tokens=max(left.output_tokens, right.output_tokens), cache_read_tokens=max(left.cache_read_tokens, right.cache_read_tokens), cache_creation_tokens=max(left.cache_creation_tokens, right.cache_creation_tokens), cache_creation_5m_tokens=max(left.cache_creation_5m_tokens, right.cache_creation_5m_tokens), cache_creation_1h_tokens=max(left.cache_creation_1h_tokens, right.cache_creation_1h_tokens), reported_cost_usd=max(v for v in (left.reported_cost_usd, right.reported_cost_usd) if v is not None) if any(v is not None for v in (left.reported_cost_usd, right.reported_cost_usd)) else None, cost_basis=preferred.cost_basis or other.cost_basis, project_id=preferred.project_id or other.project_id, is_final=left.is_final or right.is_final, metadata=metadata)

def _preferred(left: UsageRecord, right: UsageRecord):
    def preference_key(record: UsageRecord):
        present = sum(
            value is not None
            for value in (
                record.timestamp,
                record.session_id,
                record.prompt_id,
                record.request_id,
                record.message_id,
                record.agent_id,
                record.query_source,
                record.model_raw,
                record.model_resolved,
                record.reported_cost_usd,
                record.cost_basis,
                record.agent_name,
            )
        )
        tokens = (
            record.input_tokens
            + record.output_tokens
            + record.cache_read_tokens
            + record.cache_creation_tokens
            + record.cache_creation_5m_tokens
            + record.cache_creation_1h_tokens
        )
        stable_tiebreaker = json.dumps(
            record_to_dict(record),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return (
            1 if record.is_final else 0,
            present,
            tokens,
            record.metadata.collected_at,
            stable_tiebreaker,
        )

    if preference_key(right) > preference_key(left):
        return right, left
    return left, right

def _latest(left, right):
    if left is None: return right
    if right is None: return left
    return max(left, right)

def _sort_key(record: UsageRecord):
    return (record.timestamp or datetime.min.replace(tzinfo=timezone.utc), record.session_id or "", record.agent_scope, record.request_id or "", record.message_id or "", record.record_id)

__all__ = ["dedupe_usage"]
