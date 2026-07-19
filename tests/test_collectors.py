from __future__ import annotations
import test_bootstrap
from datetime import datetime, timezone
from importlib.resources import files
import json
import unittest
from claude_code_data_kit.collectors import ClaudeHookAdapter, ClaudeOTelAdapter, ClaudeStatusLineAdapter, ClaudeTranscriptAdapter
from claude_code_data_kit.records import EvidenceLevel, MessageRecord, ModelObservationRecord, SessionEvent, StatusSnapshot, TimestampBasis, UsageRecord, record_to_dict
NOW = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)
ROOT = files('claude_code_data_kit').joinpath('_fixtures')

def load(name: str):
    return json.loads(ROOT.joinpath(name).read_text(encoding='utf-8'))

class CollectorTests(unittest.TestCase):

    def test_otel_normalizes_usage_and_model_observation(self):
        batch = ClaudeOTelAdapter().parse_event(load('otel_api_request.json'), collected_at=NOW)
        usage = [record for record in batch.records if isinstance(record, UsageRecord)]
        observations = [record for record in batch.records if isinstance(record, ModelObservationRecord)]
        self.assertEqual(len(usage), 1)
        self.assertEqual(usage[0].cache_read_tokens, 1000)
        self.assertEqual(usage[0].metadata.source_version, '2.1.214')
        self.assertEqual(usage[0].agent_name, 'main')
        self.assertEqual(usage[0].request_id, 'request-synthetic')
        self.assertEqual(len(observations), 1)
        self.assertIsNone(observations[0].serving_model)
        self.assertEqual(observations[0].evidence_quality, EvidenceLevel.LOCAL_IMPLEMENTATION_DETAIL)
        self.assertEqual(observations[0].observed_at, datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertIn('event.sequence', observations[0].metadata.field_evidence)
        self.assertIn('otel_model_fields_are_version_sensitive_client_visible_evidence', batch.warnings)

    def test_statusline_uses_effort_level_only(self):
        payload = load('statusline_main.json')
        payload['effort'] = {'level': 'high', 'max_tokens': 1000}
        observation = next((record for record in ClaudeStatusLineAdapter().parse_main(payload, collected_at=NOW).records if isinstance(record, ModelObservationRecord)))
        self.assertEqual(observation.effort, 'high')

    def test_otel_api_error_preserves_request_evidence(self):
        payload = {'event': {'name': 'claude_code.api_error', 'timestamp': '2026-01-01T00:00:02Z'}, 'session': {'id': 'session-synthetic'}, 'prompt': {'id': 'prompt-synthetic'}, 'request_id': 'request-error', 'model': 'claude-sonnet-4-5', 'query_source': 'agent', 'agent': {'name': 'worker'}, 'attributes': {'attempt': 2, 'error.type': 'timeout'}, 'resource': {'attributes': {'service.version': '2.1.214'}}}
        batch = ClaudeOTelAdapter().parse_event(payload, collected_at=NOW)
        event = next((record for record in batch.records if isinstance(record, SessionEvent)))
        observation = next((record for record in batch.records if isinstance(record, ModelObservationRecord)))
        self.assertEqual(event.event_type, 'api_error')
        self.assertEqual(observation.request_declared_model, 'claude-sonnet-4-5')
        self.assertIsNone(observation.response_reported_model)
        self.assertEqual(observation.attempt, 2)
        self.assertEqual(observation.request_id, 'request-error')
        self.assertEqual(observation.query_source, 'agent')
        self.assertEqual(observation.agent_name, 'worker')

    def test_otel_refusal_model_is_request_evidence_only(self):
        payload = {'event': {'name': 'claude_code.api_refusal', 'timestamp': '2026-01-01T00:00:03Z'}, 'request_id': 'request-refusal', 'model': 'claude-opus-4-6', 'attributes': {'server_fallback_hop': True}}
        observation = next((record for record in ClaudeOTelAdapter().parse_event(payload, collected_at=NOW).records if isinstance(record, ModelObservationRecord)))
        self.assertEqual(observation.request_declared_model, 'claude-opus-4-6')
        self.assertIsNone(observation.response_reported_model)
        self.assertTrue(observation.server_fallback_hop)

    def test_otel_assistant_response_keeps_metadata_not_content(self):
        payload = {'event': {'name': 'claude_code.assistant_response', 'timestamp': '2026-01-01T00:00:04Z'}, 'session': {'id': 'session-synthetic'}, 'request_id': 'request-response', 'model': 'claude-opus-4-6', 'attributes': {'message.id': 'message-response', 'response_length': 123, 'raw_response': 'must-not-be-retained'}}
        batch = ClaudeOTelAdapter().parse_event(payload, collected_at=NOW)
        message = next((record for record in batch.records if isinstance(record, MessageRecord)))
        encoded = record_to_dict(message)
        self.assertEqual(message.content_length, 123)
        self.assertNotIn('raw_response', encoded)
        self.assertNotIn('content', encoded)

    def test_hook_missing_timestamp_uses_collector_observed_basis(self):
        payload = {'hook_event_name': 'UserPromptSubmit', 'session_id': 'session-synthetic', 'prompt_id': 'prompt-missing-ts'}
        event = next((record for record in ClaudeHookAdapter().parse_event(payload, source_version='2.1.214', collected_at=NOW).records if isinstance(record, SessionEvent)))
        self.assertEqual(event.timestamp, NOW)
        self.assertEqual(event.timestamp_basis, TimestampBasis.COLLECTOR_OBSERVED_AT)

    def test_hook_agent_resolved_model_is_local_warned_and_gated(self):
        payload = load('hook_agent_posttooluse.json')
        before = ClaudeHookAdapter().parse_event(payload, source_version='2.1.173', collected_at=NOW)
        after = ClaudeHookAdapter().parse_event(payload, source_version='2.1.214', collected_at=NOW)
        future = ClaudeHookAdapter().parse_event(payload, source_version='3.0.0', collected_at=NOW)
        self.assertFalse(any((isinstance(record, ModelObservationRecord) and record.subagent_resolved_model for record in before.records)))
        self.assertFalse(any((isinstance(record, ModelObservationRecord) and record.subagent_resolved_model for record in future.records)))
        self.assertIn('agent_resolved_model_ignored_before_2.1.174_or_unknown_version', before.warnings)
        observation = next((record for record in after.records if isinstance(record, ModelObservationRecord)))
        self.assertEqual(observation.subagent_resolved_model, 'claude-sonnet-4-5')
        self.assertEqual(observation.evidence_quality, EvidenceLevel.LOCAL_IMPLEMENTATION_DETAIL)
        evidence = observation.metadata.field_evidence['tool_response.resolvedModel']
        self.assertEqual(evidence.level, EvidenceLevel.LOCAL_IMPLEMENTATION_DETAIL)
        self.assertEqual(evidence.version_boundary.min_inclusive, '2.1.174')
        self.assertEqual(evidence.version_boundary.max_exclusive, '3.0.0')
        self.assertIn('not official-supported', evidence.note)
        self.assertIn('not authoritative', evidence.note)
        self.assertIn('never backend serving attestation', evidence.note)
        self.assertIsNone(observation.serving_model)
        self.assertIn('agent_resolved_model_is_unverified_local_implementation_detail', after.warnings)

    def test_hook_preserves_lifecycle_and_agent_usage(self):
        batch = ClaudeHookAdapter().parse_event(load('hook_agent_posttooluse.json'), source_version='2.1.214', collected_at=NOW)
        event = next((record for record in batch.records if isinstance(record, SessionEvent)))
        usage = next((record for record in batch.records if isinstance(record, UsageRecord)))
        self.assertEqual(event.event_type, 'subagent_tool_completed')
        self.assertEqual(event.result_category, 'completed')
        self.assertEqual(usage.output_tokens, 10)
        self.assertTrue(usage.is_final)
        self.assertEqual(usage.query_source, 'agent_tool')

    def test_main_statusline_uses_documented_repo_fields(self):
        snapshot = next((record for record in ClaudeStatusLineAdapter().parse_main(load('statusline_main.json'), collected_at=NOW).records if isinstance(record, StatusSnapshot)))
        self.assertEqual(snapshot.repo_host, 'synthetic-host')
        self.assertEqual(snapshot.repo_owner, 'synthetic-owner')
        self.assertEqual(snapshot.repo_name, 'synthetic-repo')
        self.assertEqual(snapshot.pr_number, 7)
        self.assertIn('workspace.repo.host', snapshot.metadata.field_evidence)
        self.assertNotIn('workspace.repo_dir', snapshot.metadata.field_evidence)

    def test_main_statusline_model_is_not_serving_attestation(self):
        observation = next((record for record in ClaudeStatusLineAdapter().parse_main(load('statusline_main.json'), collected_at=NOW).records if isinstance(record, ModelObservationRecord)))
        self.assertEqual(observation.agent_name, 'main')
        self.assertIsNone(observation.serving_model)
        self.assertIn('statusline_model_is_not_backend_serving_attestation', observation.metadata.warnings)

    def test_subagent_statusline_version_gate(self):
        payload = load('statusline_subagents.json')
        old = dict(payload)
        old['version'] = '2.1.204'
        future = dict(payload)
        future['version'] = '3.0.0'
        old_batch = ClaudeStatusLineAdapter().parse_subagents(old, collected_at=NOW)
        future_batch = ClaudeStatusLineAdapter().parse_subagents(future, collected_at=NOW)
        new_batch = ClaudeStatusLineAdapter().parse_subagents(payload, collected_at=NOW)
        self.assertFalse(any((isinstance(record, ModelObservationRecord) for record in old_batch.records)))
        self.assertFalse(any((isinstance(record, ModelObservationRecord) for record in future_batch.records)))
        self.assertIn('subagent_model_fields_ignored_before_2.1.205_or_unknown_version', old_batch.warnings)
        observation = next((record for record in new_batch.records if isinstance(record, ModelObservationRecord)))
        self.assertEqual(observation.evidence_quality, EvidenceLevel.OFFICIAL_DOCUMENTED_VERSION_SENSITIVE)
        self.assertIsNone(observation.serving_model)

    def test_transcript_is_version_gated_deduped_and_undated(self):
        lines = ROOT.joinpath('transcript_2_1_214.jsonl').read_text(encoding='utf-8').splitlines()
        unsupported = ClaudeTranscriptAdapter().parse_jsonl(lines, source_version='3.0.0', collected_at=NOW)
        supported = ClaudeTranscriptAdapter().parse_jsonl(lines, source_version='2.1.214', collected_at=NOW)
        usages = [record for record in supported.records if isinstance(record, UsageRecord)]
        self.assertEqual(unsupported.records, ())
        self.assertIn('unsupported_or_unknown_transcript_version', unsupported.warnings)
        self.assertEqual(len(usages), 2)
        agent = next((record for record in usages if record.agent_id == 'agent-synthetic'))
        undated = next((record for record in usages if record.agent_id == 'agent-undated'))
        self.assertEqual(agent.output_tokens, 25)
        self.assertTrue(agent.is_final)
        self.assertIsNone(undated.timestamp)
        self.assertEqual(undated.timestamp_basis, TimestampBasis.UNDATED)
        self.assertIn('missing_timestamp_not_backfilled_from_mtime', supported.warnings)

    def test_transcript_string_and_line_iterables_match(self):
        text = ROOT.joinpath('transcript_2_1_214.jsonl').read_text(encoding='utf-8')
        from_text = ClaudeTranscriptAdapter().parse_jsonl(text, source_version='2.1.214', collected_at=NOW)
        from_lines = ClaudeTranscriptAdapter().parse_lines(text.splitlines(), source_version='2.1.214', collected_at=NOW)
        self.assertEqual([record_to_dict(record) for record in from_text.records], [record_to_dict(record) for record in from_lines.records])
if __name__ == '__main__':
    unittest.main()
