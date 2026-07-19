from __future__ import annotations
from datetime import datetime
from typing import Any, Mapping, Optional
from ..records import CollectorBatch, EvidenceLevel, ModelIntentRecord, ModelObservationRecord, SessionEvent, SourceKind, TimestampBasis, UsageRecord, VersionBoundary, stable_id, utc_now
from ..versioning import version_allows
from ._common import as_bool, as_float, as_int, first, local_evidence, make_metadata, official_evidence, parse_timestamp
_AGENT_RESOLVED_MODEL_BOUNDARY = VersionBoundary(min_inclusive='2.1.174', max_exclusive='3.0.0')
_AGENT_RESOLVED_MODEL_NOTE = 'Unverified local implementation field observed at Agent PostToolUse.tool_response.resolvedModel; not official-supported, not authoritative, and never backend serving attestation.'

class ClaudeHookAdapter:
    """Normalize Claude Code hook metadata without retaining raw payload content."""
    source = SourceKind.CLAUDE_HOOK

    def parse_event(self, payload: Mapping[str, Any], *, source_version: Optional[str], collected_at: Optional[datetime]=None) -> CollectorBatch:
        observed_at = collected_at or utc_now()
        source_timestamp = parse_timestamp(payload.get('timestamp'))
        timestamp = source_timestamp or observed_at
        timestamp_basis = TimestampBasis.SOURCE_TIMESTAMP if source_timestamp is not None else TimestampBasis.COLLECTOR_OBSERVED_AT
        event_name = _string(payload.get('hook_event_name'))
        if not event_name:
            return CollectorBatch((), ('hook_event_name_missing',))
        session_id = _string(payload.get('session_id'))
        prompt_id = _string(payload.get('prompt_id'))
        agent_id = _string(first(payload, 'agent_id', 'tool_response.agentId'))
        tool_name = _string(payload.get('tool_name'))
        tool_use_id = _string(payload.get('tool_use_id'))
        warnings: list[str] = []
        evidence = {'hook_event_name': official_evidence(self.source, source_version, note='Documented Claude Code hook input path and event discriminator.'), 'session_id': official_evidence(self.source, source_version, note='Documented Claude Code hook session identifier.'), 'prompt_id': official_evidence(self.source, source_version, note='Documented Claude Code hook prompt identifier.')}

        def metadata(extra_evidence: Optional[Mapping[str, Any]]=None, extra_warnings: tuple[str, ...]=()):
            field_evidence = dict(evidence)
            field_evidence.update(extra_evidence or {})
            return make_metadata(self.source, source_version=source_version, collected_at=observed_at, field_evidence=field_evidence, warnings=(*warnings, *extra_warnings))
        records = []
        if event_name == 'SessionStart':
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='session_start', result_category=_string(payload.get('source')), agent_id=agent_id, tool_name=None, tool_use_id=None, interrupted=None, timestamp_basis=timestamp_basis, metadata=metadata()))
            model = _string(payload.get('model'))
            if model:
                model_metadata = metadata({'model': official_evidence(self.source, source_version, note='Documented SessionStart model label; client-visible metadata only, not backend serving attestation.')}, ('session_start_model_is_not_backend_serving_attestation',))
                records.append(ModelObservationRecord(record_id=stable_id('modelobs', self.source.value, session_id, prompt_id, timestamp.isoformat(), model, 'session-start'), observed_at=timestamp, session_id=session_id, prompt_id=prompt_id, request_id=None, message_id=None, agent_id=agent_id, query_source='session_start', request_declared_model=None, response_reported_model=None, usage_reported_model=None, statusline_model=model, subagent_resolved_model=None, serving_model=None, speed=None, effort=_string(payload.get('effort')), attempt=None, fallback_reason=None, server_fallback_hop=None, evidence_quality=EvidenceLevel.OFFICIAL_SUPPORTED, metadata=model_metadata))
        elif event_name == 'UserPromptSubmit':
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='prompt_submitted', result_category='started', agent_id=agent_id, tool_name=None, tool_use_id=None, interrupted=None, timestamp_basis=timestamp_basis, metadata=metadata()))
        elif event_name == 'Stop':
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='turn_stopped', result_category='success', agent_id=agent_id, tool_name=None, tool_use_id=None, interrupted=False, timestamp_basis=timestamp_basis, metadata=metadata()))
        elif event_name == 'StopFailure':
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='turn_failed', result_category=_string(payload.get('error')) or 'unknown', agent_id=agent_id, tool_name=None, tool_use_id=None, interrupted=False, timestamp_basis=timestamp_basis, metadata=metadata()))
        elif event_name == 'PostToolUseFailure':
            interrupted = as_bool(payload.get('is_interrupt'))
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='tool_failed', result_category='interrupted' if interrupted else 'failed', agent_id=agent_id, tool_name=tool_name, tool_use_id=tool_use_id, interrupted=interrupted, timestamp_basis=timestamp_basis, metadata=metadata()))
        elif event_name in {'SubagentStart', 'SubagentStop'}:
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='subagent_started' if event_name == 'SubagentStart' else 'subagent_stopped', result_category=_string(payload.get('agent_type')), agent_id=agent_id, tool_name=None, tool_use_id=None, interrupted=None, timestamp_basis=timestamp_basis, metadata=metadata()))
        elif event_name in {'PreCompact', 'PostCompact'}:
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='compact_started' if event_name == 'PreCompact' else 'compact_completed', result_category=_string(payload.get('trigger')), agent_id=agent_id, tool_name=None, tool_use_id=None, interrupted=None, timestamp_basis=timestamp_basis, metadata=metadata()))
        elif event_name == 'SessionEnd':
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='session_end', result_category=_string(payload.get('reason')), agent_id=agent_id, tool_name=None, tool_use_id=None, interrupted=None, timestamp_basis=timestamp_basis, metadata=metadata()))
        elif event_name == 'PostToolUse' and tool_name == 'Agent':
            tool_input = payload.get('tool_input') if isinstance(payload.get('tool_input'), Mapping) else {}
            tool_response = payload.get('tool_response') if isinstance(payload.get('tool_response'), Mapping) else {}
            requested_model = _string(tool_input.get('model'))
            resolved_model = _string(tool_response.get('resolvedModel'))
            agent_id = _string(tool_response.get('agentId')) or agent_id
            if requested_model:
                records.append(ModelIntentRecord(record_id=stable_id('modelintent', self.source.value, session_id, prompt_id, agent_id, tool_use_id, requested_model), observed_at=timestamp, session_id=session_id, prompt_id=prompt_id, agent_id=agent_id, selected_model=requested_model, requested_alias=requested_model if _looks_like_alias(requested_model) else None, client_resolved_model=None, config_scope='subagent-invocation', provider=None, switch_reason='subagent_model_override', metadata=metadata()))
            if resolved_model:
                if version_allows(source_version, _AGENT_RESOLVED_MODEL_BOUNDARY):
                    resolved_warning = 'agent_resolved_model_is_unverified_local_implementation_detail'
                    warnings.append(resolved_warning)
                    resolved_metadata = metadata({'tool_response.resolvedModel': local_evidence(self.source, source_version, min_version='2.1.174', max_version='3.0.0', note=_AGENT_RESOLVED_MODEL_NOTE)}, (resolved_warning,))
                    records.append(ModelObservationRecord(record_id=stable_id('modelobs', self.source.value, session_id, prompt_id, agent_id, tool_use_id, resolved_model), observed_at=timestamp, session_id=session_id, prompt_id=prompt_id, request_id=None, message_id=None, agent_id=agent_id, query_source='agent_tool', request_declared_model=requested_model, response_reported_model=None, usage_reported_model=None, statusline_model=None, subagent_resolved_model=resolved_model, serving_model=None, speed=None, effort=_string(payload.get('effort')), attempt=None, fallback_reason=None, server_fallback_hop=None, evidence_quality=EvidenceLevel.LOCAL_IMPLEMENTATION_DETAIL, metadata=resolved_metadata))
                    usage = tool_response.get('usage') if isinstance(tool_response.get('usage'), Mapping) else {}
                    if usage:
                        records.append(UsageRecord(record_id=stable_id('usage', self.source.value, session_id, prompt_id, agent_id, tool_use_id, resolved_model), timestamp=timestamp, timestamp_basis=timestamp_basis, session_id=session_id, prompt_id=prompt_id, request_id=None, message_id=None, agent_id=agent_id, query_source='agent_tool', model_raw=resolved_model, model_resolved=resolved_model, input_tokens=as_int(usage.get('input_tokens')), output_tokens=as_int(usage.get('output_tokens')), cache_read_tokens=as_int(usage.get('cache_read_input_tokens')), cache_creation_tokens=as_int(usage.get('cache_creation_input_tokens')), reported_cost_usd=as_float(tool_response.get('costUSD')), cost_basis='claude_reported_estimated_cost_usd' if tool_response.get('costUSD') is not None else None, is_final=_string(tool_response.get('status')) == 'completed', metadata=resolved_metadata))
                else:
                    warnings.append('agent_resolved_model_ignored_before_2.1.174_or_unknown_version')
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='subagent_tool_completed', result_category=_string(tool_response.get('status')), agent_id=agent_id, tool_name=tool_name, tool_use_id=tool_use_id, interrupted=False, timestamp_basis=timestamp_basis, metadata=metadata()))
        elif event_name in {'PreToolUse', 'PostToolUse'}:
            records.append(self._session_event(timestamp, session_id, prompt_id, event_type='tool_started' if event_name == 'PreToolUse' else 'tool_succeeded', result_category='started' if event_name == 'PreToolUse' else 'success', agent_id=agent_id, tool_name=tool_name, tool_use_id=tool_use_id, interrupted=False if event_name == 'PostToolUse' else None, timestamp_basis=timestamp_basis, metadata=metadata()))
        else:
            warnings.append(f'hook_event_unhandled:{event_name}')
        return CollectorBatch(tuple(records), tuple(dict.fromkeys(warnings)))

    def _session_event(self, timestamp: datetime, session_id: Optional[str], prompt_id: Optional[str], *, event_type: str, result_category: Optional[str], agent_id: Optional[str], tool_name: Optional[str], tool_use_id: Optional[str], interrupted: Optional[bool], timestamp_basis: TimestampBasis, metadata) -> SessionEvent:
        return SessionEvent(record_id=stable_id('event', self.source.value, session_id, prompt_id, agent_id, event_type, tool_use_id, timestamp.isoformat()), timestamp=timestamp, timestamp_basis=timestamp_basis, session_id=session_id, prompt_id=prompt_id, event_type=event_type, result_category=result_category, agent_id=agent_id, project_id=None, tool_name=tool_name, tool_use_id=tool_use_id, interrupted=interrupted, metadata=metadata)

def _looks_like_alias(value: str) -> bool:
    lowered = value.lower().strip()
    return lowered in {'opus', 'sonnet', 'haiku', 'fable', 'best', 'default', 'inherit', 'opusplan'} or lowered.endswith('[1m]')

def _string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
__all__ = ['ClaudeHookAdapter']
