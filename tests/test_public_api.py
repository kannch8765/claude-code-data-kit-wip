from __future__ import annotations

import importlib.metadata
from pathlib import Path
import re
import unittest

import test_bootstrap
import claude_code_data_kit as kit
import claude_code_data_kit.collectors as collectors
import claude_code_data_kit.dedupe as dedupe
import claude_code_data_kit.lab as lab
import claude_code_data_kit.records as records
import claude_code_data_kit.routing as routing
import claude_code_data_kit.versioning as versioning

EXPECTED_TOP_LEVEL = [
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


class PublicApiTests(unittest.TestCase):
    def test_module_allowlists_exist(self):
        for module in (kit, collectors, records, dedupe, routing, versioning, lab):
            self.assertTrue(module.__all__)
        self.assertNotIn("nested_get", collectors.__all__)

    def test_top_level_allowlist_is_exact_and_intentional(self):
        self.assertEqual(kit.__all__, EXPECTED_TOP_LEVEL)
        self.assertIs(kit.CanonicalRecord, records.CanonicalRecord)
        self.assertIs(kit.stable_id, records.stable_id)
        self.assertIs(kit.dedupe_usage, dedupe.dedupe_usage)
        self.assertIs(kit.DarioSeizer, routing.DarioSeizer)
        self.assertIs(kit.RoutingAccumulator, routing.RoutingAccumulator)

    def test_schema_and_package_version(self):
        self.assertEqual(kit.SCHEMA_VERSION, "1.0.0")
        pyproject = (Path(__file__).parents[1] / "pyproject.toml").read_text(
            encoding="utf-8"
        )
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        self.assertIsNotNone(match)
        self.assertEqual(kit.__version__, match.group(1))
        try:
            installed = importlib.metadata.version("claude-code-data-kit")
        except importlib.metadata.PackageNotFoundError:
            installed = None
        if installed is not None:
            self.assertEqual(kit.__version__, installed)


if __name__ == "__main__":
    unittest.main()
