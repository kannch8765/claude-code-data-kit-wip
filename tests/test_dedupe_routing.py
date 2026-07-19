from __future__ import annotations
import test_bootstrap
from dataclasses import replace
from datetime import datetime, timezone
import unittest
from claude_code_data_kit.dedupe import dedupe_usage
from claude_code_data_kit.records import CanonicalMetadata, EvidenceLevel, ModelIntentRecord, ModelObservationRecord, RoutingClassification, SourceKind, TimestampBasis, UsageRecord, record_to_dict, stable_id
from claude_code_data_kit.routing import DarioSeizer, RoutingAccumulator
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

def metadata(source: SourceKind=SourceKind.SYNTHETIC_FIXTURE) -> CanonicalMetadata:
    return CanonicalMetadata(source=source, collected_at=NOW, source_version='2.1.214')

def intent(selected: str, *, resolved: str | None=None, agent_id: str | None=None, switch_reason: str | None=None, request_id: str | None=None, prompt_id: str='prompt-synthetic') -> ModelIntentRecord:
    return ModelIntentRecord(record_id=stable_id('intent', selected, resolved, agent_id, switch_reason, request_id, prompt_id), observed_at=NOW, session_id='session-synthetic', prompt_id=prompt_id, agent_id=agent_id, selected_model=selected, requested_alias=selected if selected in {'opus', 'sonnet', 'haiku', 'fable', 'opusplan'} else None, client_resolved_model=resolved, config_scope='session', provider='anthropic', switch_reason=switch_reason, metadata=metadata(), request_id=request_id)

def observation(*, request_model: str | None=None, response_model: str | None=None, usage_model: str | None=None, subagent_model: str | None=None, agent_id: str | None=None, agent_name: str | None=None, query_source: str | None='synthetic', fallback_reason: str | None=None, server_fallback_hop: bool | None=None, request_id: str | None='request-synthetic', prompt_id: str='prompt-synthetic', observed_at: datetime=NOW) -> ModelObservationRecord:
    return ModelObservationRecord(record_id=stable_id('obs', request_model, response_model, usage_model, subagent_model, agent_id, agent_name, query_source, fallback_reason, request_id, prompt_id, observed_at.isoformat()), observed_at=observed_at, session_id='session-synthetic', prompt_id=prompt_id, request_id=request_id, message_id='message-synthetic', agent_id=agent_id, agent_name=agent_name, query_source=query_source, request_declared_model=request_model, response_reported_model=response_model, usage_reported_model=usage_model, statusline_model=None, subagent_resolved_model=subagent_model, serving_model=None, speed=None, effort=None, attempt=1, fallback_reason=fallback_reason, server_fallback_hop=server_fallback_hop, evidence_quality=EvidenceLevel.LOCAL_IMPLEMENTATION_DETAIL, metadata=metadata(SourceKind.CLAUDE_OTEL))

def usage(*, agent_id: str, request_id: str, output: int, message_id: str='message-synthetic') -> UsageRecord:
    return UsageRecord(record_id=stable_id('usage', agent_id, request_id, output), timestamp=NOW, timestamp_basis=TimestampBasis.SOURCE_TIMESTAMP, session_id='session-synthetic', prompt_id='prompt-synthetic', request_id=request_id, message_id=message_id, agent_id=agent_id, query_source='synthetic', model_raw='claude-sonnet-4-5', model_resolved='claude-sonnet-4-5', output_tokens=output, is_final=output > 10, metadata=metadata(SourceKind.CLAUDE_TRANSCRIPT_JSONL))

class DedupeTests(unittest.TestCase):

    def test_dedupe_is_order_independent(self):
        early = usage(agent_id='agent-a', request_id='request-1', output=5)
        final = usage(agent_id='agent-a', request_id='request-1', output=25)
        left = dedupe_usage([early, final])
        right = dedupe_usage([final, early])
        self.assertEqual(record_to_dict(left[0]), record_to_dict(right[0]))
        self.assertEqual(left[0].output_tokens, 25)

    def test_agent_scope_isolation_prevents_false_dedupe(self):
        first = usage(agent_id='agent-a', request_id='request-1', output=5)
        second = usage(agent_id='agent-b', request_id='request-1', output=5)
        self.assertEqual(len(dedupe_usage([first, second])), 2)

    def test_different_request_ids_do_not_dedupe(self):
        first = usage(agent_id='agent-a', request_id='request-1', output=5)
        second = usage(agent_id='agent-a', request_id='request-2', output=5)
        self.assertEqual(len(dedupe_usage([first, second])), 2)

    def test_equal_scores_use_stable_final_tiebreaker(self):
        left = replace(
            usage(agent_id='agent-a', request_id='request-1', output=5),
            record_id='usage-alpha',
            model_raw='model-alpha',
            model_resolved='model-alpha',
            metadata=metadata(SourceKind.CLAUDE_OTEL),
        )
        right = replace(
            usage(agent_id='agent-a', request_id='request-1', output=5),
            record_id='usage-beta',
            model_raw='model-beta',
            model_resolved='model-beta',
            metadata=metadata(SourceKind.CLAUDE_TRANSCRIPT_JSONL),
        )
        forward = record_to_dict(dedupe_usage([left, right])[0])
        reverse = record_to_dict(dedupe_usage([right, left])[0])
        self.assertEqual(forward, reverse)
        self.assertEqual(forward['record_id'], 'usage-beta')
        self.assertEqual(forward['model_resolved'], 'model-beta')
        self.assertEqual(forward['metadata']['source'], 'claude-transcript-jsonl')

class RoutingTests(unittest.TestCase):

    def setUp(self):
        self.engine = DarioSeizer()

    def test_alias_resolution_is_not_fallback(self):
        result = self.engine.assess([intent('opus', resolved='claude-opus-4-6')], [observation(request_model='claude-opus-4-6', response_model='claude-opus-4-6')])
        self.assertEqual(result.classification, RoutingClassification.ALIAS_RESOLUTION)
        self.assertFalse(result.backend_attestation_available)
        self.assertIsNone(result.serving_model)

    def test_documented_fallback_requires_explicit_signal(self):
        result = self.engine.assess([intent('claude-opus-4-6', resolved='claude-opus-4-6')], [observation(request_model='claude-opus-4-6', response_model='claude-sonnet-4-5', fallback_reason='explicit synthetic switch notice')])
        self.assertEqual(result.classification, RoutingClassification.DOCUMENTED_FALLBACK)

    def test_plain_mismatch_is_not_accused_as_fallback(self):
        result = self.engine.assess([intent('claude-opus-4-6', resolved='claude-opus-4-6')], [observation(request_model='claude-opus-4-6', response_model='claude-sonnet-4-5')])
        self.assertEqual(result.classification, RoutingClassification.OBSERVED_MODEL_MISMATCH)
        self.assertIn('mismatch_has_no_documented_cause', result.warnings)

    def test_full_model_ids_in_one_family_are_not_equivalent(self):
        result = self.engine.assess([intent('claude-opus-4-6', resolved='claude-opus-4-6')], [observation(request_model='claude-opus-4-6', response_model='claude-opus-4-8')])
        self.assertEqual(result.classification, RoutingClassification.OBSERVED_MODEL_MISMATCH)
        self.assertFalse(result.externally_reported_match)

    def test_refusal_hop_plus_final_response_is_documented_fallback(self):
        refusal = observation(request_model='claude-opus-4-6', response_model=None, server_fallback_hop=True, request_id='request-1')
        final = observation(request_model='claude-opus-4-6', response_model='claude-sonnet-4-5', request_id='request-1')
        result = self.engine.assess([intent('claude-opus-4-6', resolved='claude-opus-4-6', request_id='request-1')], [refusal, final])
        self.assertEqual(result.classification, RoutingClassification.DOCUMENTED_FALLBACK)

    def test_multi_request_assessment_requires_explicit_scope(self):
        first_intent = intent('claude-opus-4-6', resolved='claude-opus-4-6', request_id='request-1')
        second_intent = intent('claude-sonnet-4-5', resolved='claude-sonnet-4-5', request_id='request-2')
        first_observation = observation(request_model='claude-opus-4-6', response_model='claude-opus-4-6', request_id='request-1')
        second_observation = observation(request_model='claude-sonnet-4-5', response_model='claude-sonnet-4-5', request_id='request-2')
        accumulator = RoutingAccumulator()
        for record in (first_intent, second_intent):
            accumulator.ingest_intent(record)
        for record in (first_observation, second_observation):
            accumulator.ingest_observation(record)
        with self.assertRaisesRegex(ValueError, 'request_id'):
            accumulator.assessment()
        later = accumulator.assessment(request_id='request-2')
        self.assertEqual(later.requested_model, 'claude-sonnet-4-5')
        self.assertEqual(later.reported_model, 'claude-sonnet-4-5')
        self.assertEqual(later.classification, RoutingClassification.EXTERNALLY_REPORTED_MATCH)

    def test_main_agent_name_does_not_imply_subagent_scope(self):
        result = self.engine.assess([intent('claude-opus-4-6', resolved='claude-opus-4-6', request_id='request-synthetic')], [observation(request_model='claude-opus-4-6', response_model='claude-opus-4-6', agent_name='main')])
        self.assertEqual(result.classification, RoutingClassification.EXTERNALLY_REPORTED_MATCH)
        self.assertTrue(result.externally_reported_match)

    def test_prompt_scope_is_applied_before_request_ambiguity(self):
        result = self.engine.assess([intent('claude-opus-4-6', resolved='claude-opus-4-6', request_id='request-1', prompt_id='prompt-1'), intent('claude-sonnet-4-5', resolved='claude-sonnet-4-5', request_id='request-2', prompt_id='prompt-2')], [observation(request_model='claude-opus-4-6', response_model='claude-opus-4-6', request_id='request-1', prompt_id='prompt-1'), observation(request_model='claude-sonnet-4-5', response_model='claude-sonnet-4-5', request_id='request-2', prompt_id='prompt-2')], prompt_id='prompt-2')
        self.assertEqual(result.request_id, 'request-2')
        self.assertEqual(result.requested_model, 'claude-sonnet-4-5')

    def test_null_request_intent_is_limited_to_selected_prompt(self):
        result = self.engine.assess([intent('claude-opus-4-6', resolved='claude-opus-4-6', prompt_id='prompt-synthetic'), intent('claude-sonnet-4-5', resolved='claude-sonnet-4-5', prompt_id='prompt-other')], [observation(request_model='claude-opus-4-6', response_model='claude-opus-4-6', request_id='request-synthetic', prompt_id='prompt-synthetic')], request_id='request-synthetic')
        self.assertEqual(result.prompt_id, 'prompt-synthetic')
        self.assertEqual(result.requested_model, 'claude-opus-4-6')

    def test_multiple_requests_inside_prompt_still_require_request_scope(self):
        intents = [intent('claude-opus-4-6', resolved='claude-opus-4-6', request_id='request-1'), intent('claude-sonnet-4-5', resolved='claude-sonnet-4-5', request_id='request-2')]
        observations = [observation(request_model='claude-opus-4-6', response_model='claude-opus-4-6', request_id='request-1'), observation(request_model='claude-sonnet-4-5', response_model='claude-sonnet-4-5', request_id='request-2')]
        with self.assertRaisesRegex(ValueError, 'request_id'):
            self.engine.assess(intents, observations, prompt_id='prompt-synthetic')

    def test_subagent_scope_is_not_main_session_mismatch(self):
        result = self.engine.assess([intent('sonnet', agent_id='agent-a')], [observation(subagent_model='claude-sonnet-4-5', agent_id='agent-a', request_id=None)], agent_id='agent-a')
        self.assertEqual(result.classification, RoutingClassification.SUBAGENT_SCOPE)

    def test_agent_name_without_id_keeps_subagent_scope(self):
        result = self.engine.assess([intent('sonnet')], [observation(agent_name='worker', query_source=None, request_id=None)])
        self.assertEqual(result.classification, RoutingClassification.SUBAGENT_SCOPE)
        self.assertEqual(result.agent_name, 'worker')

    def test_collector_gap_and_ambiguous(self):
        gap = self.engine.assess([], [])
        ambiguous = self.engine.assess([intent('opus')], [observation(response_model='claude-opus-4-6'), observation(response_model='claude-sonnet-4-5', observed_at=NOW.replace(microsecond=1))])
        self.assertEqual(gap.classification, RoutingClassification.COLLECTOR_GAP)
        self.assertEqual(ambiguous.classification, RoutingClassification.AMBIGUOUS)

    def test_out_of_order_ingest_produces_same_assessment(self):
        model_intent = intent('claude-opus-4-6', resolved='claude-opus-4-6')
        model_observation = observation(request_model='claude-opus-4-6', response_model='claude-opus-4-6')
        first = RoutingAccumulator()
        first.ingest_intent(model_intent)
        first.ingest_observation(model_observation)
        second = RoutingAccumulator()
        second.ingest_observation(model_observation)
        second.ingest_intent(model_intent)
        self.assertEqual(record_to_dict(first.assessment()), record_to_dict(second.assessment()))
if __name__ == '__main__':
    unittest.main()
