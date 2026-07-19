from __future__ import annotations
from datetime import datetime
from typing import Any, Mapping, Optional
from ..records import CollectorBatch, EvidenceLevel, MessageRecord, ModelObservationRecord, SessionEvent, SourceKind, TimestampBasis, UsageRecord, stable_id, utc_now
from ._common import as_bool, as_float, as_int, first, local_evidence, make_metadata, parse_timestamp, source_version_from_resource

class ClaudeOTelAdapter:
    """Normalize Claude Code OTel metadata without retaining raw content."""
    source = SourceKind.CLAUDE_OTEL

    def parse_event(self, payload: Mapping[str, Any], *, collected_at: Optional[datetime]=None, source_version: Optional[str]=None) -> CollectorBatch:
        observed_at = collected_at or utc_now()
        attributes = _attributes(payload)
        event_name = _event_name(payload, attributes)
        source_version = source_version or source_version_from_resource(payload)
        source_timestamp = _event_timestamp(payload, attributes)
        timestamp = source_timestamp or observed_at
        warnings: list[str] = []
        if not event_name:
            return CollectorBatch((), ('otel_event_name_missing',))
        session_id = _string(_field(payload, attributes, 'session.id', 'session_id'))
        prompt_id = _string(_field(payload, attributes, 'prompt.id', 'prompt_id'))
        request_id = _string(_field(payload, attributes, 'request_id', 'request.id', 'gen_ai.request.id'))
        message_id = _string(_field(payload, attributes, 'message.id', 'message_id', 'gen_ai.response.id'))
        agent_id = _string(_field(payload, attributes, 'agent.id', 'agent_id'))
        agent_name = _string(_field(payload, attributes, 'agent.name', 'agent_name'))
        query_source = _string(_field(payload, attributes, 'query_source', 'query.source'))
        request_model = _string(_field(payload, attributes, 'gen_ai.request.model', 'request.model', 'request_model'))
        event_model = _string(_field(payload, attributes, 'model', 'gen_ai.response.model', 'response.model'))
        usage_model = _string(_field(payload, attributes, 'usage.model', 'usage_model'))
        effort = _effort_level(_field(payload, attributes, 'effort.level', 'gen_ai.request.effort.level', 'effort', 'gen_ai.request.effort'))
        speed = _string(_field(payload, attributes, 'speed', 'service_tier'))
        attempt = _optional_int(_field(payload, attributes, 'attempt', 'request.attempt'))
        event_sequence = _field(payload, attributes, 'event.sequence', 'sequence')
        evidence = {'event.name': local_evidence(self.source, source_version, note='Version-sensitive locally observed Claude Code OTel event discriminator.'), 'event.timestamp': local_evidence(self.source, source_version, note='Version-sensitive locally observed event timestamp path.'), 'session.id': local_evidence(self.source, source_version, note='Version-sensitive locally observed session identifier attribute.'), 'prompt.id': local_evidence(self.source, source_version, note='Version-sensitive locally observed prompt identifier attribute.'), 'request_id': local_evidence(self.source, source_version, note='Version-sensitive request identity aliases.'), 'event.sequence': local_evidence(self.source, source_version, note='Locally observed event ordering field.'), 'query_source': local_evidence(self.source, source_version, note='Locally observed query-source field and compatibility alias.'), 'agent.name': local_evidence(self.source, source_version, note='Locally observed agent name field and compatibility alias.')}
        if any((request_model, event_model, usage_model)):
            warnings.append('otel_model_fields_are_version_sensitive_client_visible_evidence')
            evidence.update({'request.model': local_evidence(self.source, source_version, note='Version-sensitive requested-model aliases; client-visible evidence only, not backend serving attestation.'), 'response.model': local_evidence(self.source, source_version, note='Version-sensitive response-reported model aliases; not backend serving attestation.'), 'usage.model': local_evidence(self.source, source_version, note='Version-sensitive usage-reported model aliases; not backend serving attestation.')})
        metadata = make_metadata(self.source, source_version=source_version, collected_at=observed_at, field_evidence=evidence, warnings=warnings)
        records = []
        if event_name in {'claude_code.api_request', 'api_request'}:
            usage = _usage_from_attributes(attributes)
            reported_cost = as_float(first(attributes, 'cost_usd', 'estimated_cost_usd', 'cost.usage'))
            records.append(UsageRecord(record_id=stable_id('usage', self.source.value, session_id, request_id, message_id, agent_id, event_sequence, timestamp.isoformat()), timestamp=timestamp, timestamp_basis=TimestampBasis.SOURCE_TIMESTAMP if source_timestamp else TimestampBasis.COLLECTOR_OBSERVED_AT, session_id=session_id, prompt_id=prompt_id, request_id=request_id, message_id=message_id, agent_id=agent_id, query_source=query_source, model_raw=event_model or request_model, model_resolved=event_model or request_model, input_tokens=usage['input_tokens'], output_tokens=usage['output_tokens'], cache_read_tokens=usage['cache_read_tokens'], cache_creation_tokens=usage['cache_creation_tokens'], cache_creation_5m_tokens=usage['cache_creation_5m_tokens'], cache_creation_1h_tokens=usage['cache_creation_1h_tokens'], reported_cost_usd=reported_cost, cost_basis='claude_reported_estimated_cost_usd' if reported_cost is not None else None, project_id=_anonymous_project_id(attributes), is_final=as_bool(first(attributes, 'final', 'is_final'), False) or False, metadata=metadata, agent_name=agent_name))
            records.append(_model_observation(timestamp=timestamp, session_id=session_id, prompt_id=prompt_id, request_id=request_id, message_id=message_id, agent_id=agent_id, agent_name=agent_name, query_source=query_source, request_model=request_model or event_model, response_model=None, usage_model=usage_model or event_model, speed=speed, effort=effort, attempt=attempt, fallback_reason=None, server_fallback_hop=None, metadata=metadata))
        elif event_name in {'claude_code.assistant_response', 'assistant_response'}:
            content_length = as_int(first(attributes, 'response_length', 'message_length', 'content_length'), 0)
            records.append(MessageRecord(record_id=stable_id('message', self.source.value, session_id, request_id, message_id, agent_id, event_sequence, timestamp.isoformat()), timestamp=timestamp, timestamp_basis=TimestampBasis.SOURCE_TIMESTAMP if source_timestamp else TimestampBasis.COLLECTOR_OBSERVED_AT, session_id=session_id, prompt_id=prompt_id, turn_id=_string(first(attributes, 'turn.id', 'turn_id')), message_id=message_id, request_id=request_id, agent_id=agent_id, role='assistant', content_type='text-metadata', content_length=content_length, project_id=_anonymous_project_id(attributes), metadata=metadata))
            records.append(_model_observation(timestamp=timestamp, session_id=session_id, prompt_id=prompt_id, request_id=request_id, message_id=message_id, agent_id=agent_id, agent_name=agent_name, query_source=query_source, request_model=request_model, response_model=event_model, usage_model=usage_model, speed=speed, effort=effort, attempt=attempt, fallback_reason=None, server_fallback_hop=None, metadata=metadata))
        elif event_name in {'claude_code.api_error', 'api_error'}:
            error_category = _string(_field(payload, attributes, 'error', 'error.type', 'error_category')) or 'unknown'
            records.append(SessionEvent(record_id=stable_id('event', self.source.value, event_name, session_id, prompt_id, request_id, timestamp.isoformat()), timestamp=timestamp, timestamp_basis=TimestampBasis.SOURCE_TIMESTAMP if source_timestamp else TimestampBasis.COLLECTOR_OBSERVED_AT, session_id=session_id, prompt_id=prompt_id, event_type='api_error', result_category=error_category, agent_id=agent_id, project_id=_anonymous_project_id(attributes), metadata=metadata))
            records.append(_model_observation(timestamp=timestamp, session_id=session_id, prompt_id=prompt_id, request_id=request_id, message_id=message_id, agent_id=agent_id, agent_name=agent_name, query_source=query_source, request_model=request_model or event_model, response_model=None, usage_model=None, speed=speed, effort=effort, attempt=attempt, fallback_reason=None, server_fallback_hop=None, metadata=metadata))
        elif event_name in {'claude_code.api_refusal', 'api_refusal'}:
            fallback_hop = as_bool(_field(payload, attributes, 'server_fallback_hop', 'api_refusal.server_fallback_hop'))
            reason = _string(_field(payload, attributes, 'reason', 'refusal_reason'))
            records.append(_model_observation(timestamp=timestamp, session_id=session_id, prompt_id=prompt_id, request_id=request_id, message_id=message_id, agent_id=agent_id, agent_name=agent_name, query_source=query_source, request_model=request_model or event_model, response_model=None, usage_model=None, speed=speed, effort=effort, attempt=attempt, fallback_reason=reason, server_fallback_hop=fallback_hop, metadata=metadata))
        else:
            warnings.append(f'otel_event_unhandled:{event_name}')
        return CollectorBatch(tuple(records), tuple(dict.fromkeys(warnings)))

def _attributes(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    candidates = [payload.get('attributes')]
    body = payload.get('body')
    if isinstance(body, Mapping):
        candidates.append(body.get('attributes'))
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            return {str(key): _unwrap_otel_value(value) for key, value in candidate.items()}
        if isinstance(candidate, list):
            result = {}
            for item in candidate:
                if not isinstance(item, Mapping):
                    continue
                key = item.get('key')
                if key is None:
                    continue
                result[str(key)] = _unwrap_otel_value(item.get('value'))
            if result:
                return result
    return {}

def _event_name(payload: Mapping[str, Any], attributes: Mapping[str, Any]) -> Optional[str]:
    candidates = [_field(payload, attributes, 'event.name', 'event_name', 'name')]
    body = payload.get('body')
    if isinstance(body, str):
        candidates.append(body)
    for value in candidates:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

def _event_timestamp(payload: Mapping[str, Any], attributes: Mapping[str, Any]) -> Optional[datetime]:
    for key in ('event.timestamp', 'timestamp', 'time', 'time_unix_nano', 'observed_time_unix_nano'):
        parsed = parse_timestamp(_field(payload, attributes, key))
        if parsed is not None:
            return parsed
    return None

def _field(payload: Mapping[str, Any], attributes: Mapping[str, Any], *paths: str) -> Any:
    value = first(attributes, *paths)
    if value is not None:
        return value
    value = first(payload, *paths)
    if value is not None:
        return value
    body = payload.get('body')
    if isinstance(body, Mapping):
        return first(body, *paths)
    return None

def _unwrap_otel_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    for key in ('stringValue', 'intValue', 'doubleValue', 'boolValue'):
        if key in value:
            return value[key]
    return value

def _effort_level(value: Any) -> Optional[str]:
    if isinstance(value, Mapping):
        return _string(value.get('level'))
    return _string(value)

def _usage_from_attributes(attributes: Mapping[str, Any]) -> dict[str, int]:
    return {'input_tokens': as_int(first(attributes, 'input_tokens', 'usage.input_tokens', 'gen_ai.usage.input_tokens')), 'output_tokens': as_int(first(attributes, 'output_tokens', 'usage.output_tokens', 'gen_ai.usage.output_tokens')), 'cache_read_tokens': as_int(first(attributes, 'cache_read_tokens', 'cacheRead', 'usage.cache_read_input_tokens')), 'cache_creation_tokens': as_int(first(attributes, 'cache_creation_tokens', 'cacheCreation', 'usage.cache_creation_input_tokens')), 'cache_creation_5m_tokens': as_int(first(attributes, 'cache_creation_5m_tokens', 'usage.cache_creation_5m_tokens')), 'cache_creation_1h_tokens': as_int(first(attributes, 'cache_creation_1h_tokens', 'usage.cache_creation_1h_tokens'))}

def _model_observation(*, timestamp: datetime, session_id: Optional[str], prompt_id: Optional[str], request_id: Optional[str], message_id: Optional[str], agent_id: Optional[str], agent_name: Optional[str], query_source: Optional[str], request_model: Optional[str], response_model: Optional[str], usage_model: Optional[str], speed: Optional[str], effort: Optional[str], attempt: Optional[int], fallback_reason: Optional[str], server_fallback_hop: Optional[bool], metadata) -> ModelObservationRecord:
    return ModelObservationRecord(record_id=stable_id('modelobs', SourceKind.CLAUDE_OTEL.value, session_id, prompt_id, request_id, message_id, agent_id, timestamp.isoformat(), request_model, response_model, usage_model), observed_at=timestamp, session_id=session_id, prompt_id=prompt_id, request_id=request_id, message_id=message_id, agent_id=agent_id, agent_name=agent_name, query_source=query_source, request_declared_model=request_model, response_reported_model=response_model, usage_reported_model=usage_model, statusline_model=None, subagent_resolved_model=None, serving_model=None, speed=speed, effort=effort, attempt=attempt, fallback_reason=fallback_reason, server_fallback_hop=server_fallback_hop, evidence_quality=EvidenceLevel.LOCAL_IMPLEMENTATION_DETAIL, metadata=metadata)

def _anonymous_project_id(attributes: Mapping[str, Any]) -> Optional[str]:
    return _string(first(attributes, 'project.id', 'project_id'))

def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == '':
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
__all__ = ['ClaudeOTelAdapter']
