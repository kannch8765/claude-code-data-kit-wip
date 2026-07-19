from __future__ import annotations
from datetime import datetime
import json
from typing import Any, Iterable, Mapping, Optional
from ..dedupe import dedupe_usage
from ..records import CollectorBatch, EvidenceLevel, MessageRecord, ModelObservationRecord, SessionEvent, SourceKind, TimestampBasis, UsageRecord, VersionBoundary, stable_id, utc_now
from ..versioning import version_allows
from ._common import as_float, as_int, local_evidence, make_metadata, parse_timestamp
_TRANSCRIPT_V2_BOUNDARY = VersionBoundary(min_inclusive='2.0.0', max_exclusive='3.0.0')

class ClaudeTranscriptAdapter:
    """Version-gated adapter for internal transcript JSONL metadata.

    Raw text, thinking blocks, tool inputs, and tool results are never returned.
    """
    source = SourceKind.CLAUDE_TRANSCRIPT_JSONL

    def parse_jsonl(self, lines: Iterable[str] | str, *, source_version: Optional[str], collected_at: Optional[datetime]=None) -> CollectorBatch:
        observed_at = collected_at or utc_now()
        if not version_allows(source_version, _TRANSCRIPT_V2_BOUNDARY):
            return CollectorBatch((), ('unsupported_or_unknown_transcript_version',))
        iterable = lines.splitlines() if isinstance(lines, str) else lines
        records = []
        usage_records: list[UsageRecord] = []
        warnings: list[str] = []
        for line_number, raw_line in enumerate(iterable, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                warnings.append(f'invalid_jsonl_line:{line_number}')
                continue
            if not isinstance(payload, Mapping):
                warnings.append(f'non_object_jsonl_line:{line_number}')
                continue
            batch = self.parse_record(payload, source_version=source_version, collected_at=observed_at, line_number=line_number)
            warnings.extend(batch.warnings)
            for record in batch.records:
                if isinstance(record, UsageRecord):
                    usage_records.append(record)
                else:
                    records.append(record)
        records.extend(dedupe_usage(usage_records))
        records.sort(key=lambda record: (getattr(record, 'timestamp', None) or getattr(record, 'observed_at', observed_at), record.record_id))
        return CollectorBatch(tuple(records), tuple(dict.fromkeys(warnings)))

    def parse_lines(self, lines: Iterable[str], *, source_version: Optional[str], collected_at: Optional[datetime]=None) -> CollectorBatch:
        return self.parse_jsonl(lines, source_version=source_version, collected_at=collected_at)

    def parse_record(self, payload: Mapping[str, Any], *, source_version: Optional[str], collected_at: Optional[datetime]=None, line_number: Optional[int]=None) -> CollectorBatch:
        observed_at = collected_at or utc_now()
        if not version_allows(source_version, _TRANSCRIPT_V2_BOUNDARY):
            return CollectorBatch((), ('unsupported_or_unknown_transcript_version',))
        timestamp = parse_timestamp(payload.get('timestamp'))
        timestamp_basis = TimestampBasis.SOURCE_TIMESTAMP if timestamp else TimestampBasis.UNDATED
        warnings: list[str] = []
        if timestamp is None:
            warnings.append('missing_timestamp_not_backfilled_from_mtime')
        record_type = _string(payload.get('type')) or 'unknown'
        session_id = _string(payload.get('sessionId') or payload.get('session_id'))
        prompt_id = _string(payload.get('promptId') or payload.get('prompt_id'))
        request_id = _string(payload.get('requestId') or payload.get('request_id'))
        agent_id = _string(payload.get('agentId') or payload.get('agent_id'))
        turn_id = _string(payload.get('turnId') or payload.get('turn_id'))
        message = payload.get('message') if isinstance(payload.get('message'), Mapping) else {}
        message_id = _string(message.get('id') or payload.get('messageId') or payload.get('message_id'))
        model = _string(message.get('model') or payload.get('model'))
        usage = message.get('usage') if isinstance(message.get('usage'), Mapping) else {}
        content = message.get('content')
        content_type, content_length = _content_metadata(content)
        role = _string(message.get('role')) or ('assistant' if record_type == 'assistant' else record_type)
        evidence = {'record_type': local_evidence(self.source, source_version, min_version='2.0.0', max_version='3.0.0', note='Version-sensitive internal transcript record type.'), 'message.id': local_evidence(self.source, source_version, min_version='2.0.0', max_version='3.0.0', note='Version-sensitive internal transcript message identifier.'), 'message.model': local_evidence(self.source, source_version, min_version='2.0.0', max_version='3.0.0', note='Response-reported internal transcript model label; not backend serving attestation.'), 'message.usage': local_evidence(self.source, source_version, min_version='2.0.0', max_version='3.0.0', note='Version-sensitive internal transcript usage shape.')}
        metadata_warnings = list(warnings)
        if model:
            metadata_warnings.append('transcript_model_is_not_backend_serving_attestation')
        metadata = make_metadata(self.source, source_version=source_version, collected_at=observed_at, field_evidence=evidence, warnings=metadata_warnings)
        suffix = line_number if line_number is not None else stable_id('line', repr(sorted(payload.keys())))
        records = []
        if record_type in {'assistant', 'user', 'system'}:
            records.append(MessageRecord(record_id=stable_id('message', self.source.value, session_id, request_id, message_id, agent_id, suffix), timestamp=timestamp, timestamp_basis=timestamp_basis, session_id=session_id, prompt_id=prompt_id, turn_id=turn_id, message_id=message_id, request_id=request_id, agent_id=agent_id, role=role, content_type=content_type, content_length=content_length, tool_name=None, tool_use_id=None, success=None, project_id=None, metadata=metadata))
        if record_type == 'assistant' and usage:
            records.append(UsageRecord(record_id=stable_id('usage', self.source.value, session_id, request_id, message_id, agent_id, suffix), timestamp=timestamp, timestamp_basis=timestamp_basis, session_id=session_id, prompt_id=prompt_id, request_id=request_id, message_id=message_id, agent_id=agent_id, query_source=_string(payload.get('querySource') or payload.get('query_source')), model_raw=model, model_resolved=model, input_tokens=as_int(usage.get('input_tokens')), output_tokens=as_int(usage.get('output_tokens')), cache_read_tokens=as_int(usage.get('cache_read_input_tokens')), cache_creation_tokens=as_int(usage.get('cache_creation_input_tokens')), cache_creation_5m_tokens=as_int(usage.get('cache_creation_5m_input_tokens')), cache_creation_1h_tokens=as_int(usage.get('cache_creation_1h_input_tokens')), reported_cost_usd=as_float(payload.get('costUSD') or payload.get('cost_usd')), cost_basis='claude_reported_estimated_cost_usd' if payload.get('costUSD') is not None or payload.get('cost_usd') is not None else None, project_id=None, is_final=bool(payload.get('isFinal') or payload.get('is_final')), metadata=metadata))
            if model:
                records.append(ModelObservationRecord(record_id=stable_id('modelobs', self.source.value, session_id, request_id, message_id, agent_id, suffix, model), observed_at=timestamp or observed_at, session_id=session_id, prompt_id=prompt_id, request_id=request_id, message_id=message_id, agent_id=agent_id, query_source=_string(payload.get('querySource') or payload.get('query_source')), request_declared_model=None, response_reported_model=model, usage_reported_model=model, statusline_model=None, subagent_resolved_model=None, serving_model=None, speed=_string(payload.get('speed')), effort=_string(payload.get('effort')), attempt=_optional_int(payload.get('attempt')), fallback_reason=_fallback_notice(payload), server_fallback_hop=None, evidence_quality=EvidenceLevel.LOCAL_IMPLEMENTATION_DETAIL, metadata=metadata))
        if record_type in {'summary', 'compact'}:
            records.append(SessionEvent(record_id=stable_id('event', self.source.value, session_id, prompt_id, agent_id, record_type, suffix), timestamp=timestamp, timestamp_basis=timestamp_basis, session_id=session_id, prompt_id=prompt_id, event_type='compact_record', result_category=record_type, agent_id=agent_id, project_id=None, metadata=metadata))
        if not records:
            warnings.append(f'transcript_record_unhandled:{record_type}')
        return CollectorBatch(tuple(records), tuple(dict.fromkeys(warnings)))

def _content_metadata(content: Any) -> tuple[str, int]:
    if isinstance(content, str):
        return ('text', len(content))
    if isinstance(content, list):
        types: list[str] = []
        length = 0
        for block in content:
            if isinstance(block, Mapping):
                block_type = _string(block.get('type')) or 'unknown'
                types.append(block_type)
                text = block.get('text')
                if isinstance(text, str):
                    length += len(text)
            elif isinstance(block, str):
                types.append('text')
                length += len(block)
        return ('+'.join(dict.fromkeys(types)) or 'blocks', length)
    if content is None:
        return ('empty', 0)
    return (type(content).__name__, 0)

def _fallback_notice(payload: Mapping[str, Any]) -> Optional[str]:
    for key in ('fallbackReason', 'fallback_reason', 'modelSwitchReason', 'model_switch_reason'):
        value = _string(payload.get(key))
        if value:
            return value
    return None

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
__all__ = ['ClaudeTranscriptAdapter']
