from __future__ import annotations
import test_bootstrap
from dataclasses import replace
from datetime import datetime, timezone
import unittest
from claude_code_data_kit.records import *

NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def meta(source=SourceKind.SYNTHETIC_FIXTURE): return CanonicalMetadata(source=source,collected_at=NOW)

class RecordsTests(unittest.TestCase):
    def test_schema_and_source_kinds(self):
        self.assertEqual(SCHEMA_VERSION,"1.0.0")
        self.assertNotIn("pwa" + "-tmux",[x.value for x in SourceKind])
    def test_timezone_validation(self):
        with self.assertRaisesRegex(ValueError,"timezone-aware"):
            CanonicalMetadata(source=SourceKind.SYNTHETIC_FIXTURE,collected_at=datetime(2026,1,1))
    def test_model_observation_rejects_serving_model(self):
        with self.assertRaisesRegex(ValueError,"serving_model"):
            ModelObservationRecord("x",NOW,None,None,None,None,None,None,None,None,None,None,None,"forbidden",None,None,None,None,None,None,EvidenceLevel.UNCONFIRMED,meta())
    def test_routing_rejects_attestation_and_serving_model(self):
        base=dict(assessment_id="a",session_id=None,prompt_id=None,request_id=None,agent_id=None,requested_model=None,resolved_model=None,reported_model=None,usage_model=None,serving_model=None,classification=RoutingClassification.COLLECTOR_GAP,confidence=.1,evidence_sources=(),externally_reported_match=None,backend_attestation_available=False)
        with self.assertRaisesRegex(ValueError,"backend_attestation"):
            RoutingAssessment(**{**base,"backend_attestation_available":True})
        with self.assertRaisesRegex(ValueError,"serving_model"):
            RoutingAssessment(**{**base,"serving_model":"x"})
    def test_golden_serialization(self):
        record=UsageRecord(record_id="usage-golden",timestamp=NOW,timestamp_basis=TimestampBasis.SOURCE_TIMESTAMP,session_id="session-synthetic",prompt_id="prompt-synthetic",request_id="request-synthetic",message_id="message-synthetic",agent_id=None,query_source="golden",model_raw="claude-opus-4-6",model_resolved="claude-opus-4-6",input_tokens=10,output_tokens=2,metadata=meta())
        self.assertEqual(record_to_dict(record),{
            "record_id":"usage-golden","timestamp":"2026-01-01T00:00:00+00:00","timestamp_basis":"source-timestamp","session_id":"session-synthetic","prompt_id":"prompt-synthetic","request_id":"request-synthetic","message_id":"message-synthetic","agent_id":None,"query_source":"golden","model_raw":"claude-opus-4-6","model_resolved":"claude-opus-4-6","input_tokens":10,"output_tokens":2,"cache_read_tokens":0,"cache_creation_tokens":0,"cache_creation_5m_tokens":0,"cache_creation_1h_tokens":0,"reported_cost_usd":None,"cost_basis":None,"project_id":None,"is_final":False,"metadata":{"source":"synthetic-fixture","collected_at":"2026-01-01T00:00:00+00:00","source_version":None,"schema_version":"1.0.0","field_evidence":{},"warnings":[]},"agent_name":None})
if __name__=="__main__": unittest.main()
