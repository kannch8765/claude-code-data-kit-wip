from __future__ import annotations

from importlib.resources import files
from pathlib import Path
import unittest

import test_bootstrap
from test_hygiene_rules import FICTIONAL_SENTINELS, find_violations, is_public_text_path, scan_named_texts


REPOSITORY_ROOT = Path(__file__).parents[1]
PUBLIC_ROOTS = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "CHANGELOG.md",
    REPOSITORY_ROOT / "CONTRIBUTING.md",
    REPOSITORY_ROOT / "SECURITY.md",
    REPOSITORY_ROOT / "pyproject.toml",
    REPOSITORY_ROOT / ".github",
    REPOSITORY_ROOT / "docs",
    REPOSITORY_ROOT / "src",
    REPOSITORY_ROOT / "tests",
)


def public_texts():
    for root in PUBLIC_ROOTS:
        if root.is_file():
            yield root.relative_to(REPOSITORY_ROOT).as_posix(), root.read_text(
                encoding="utf-8"
            )
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and is_public_text_path(path.as_posix()):
                yield path.relative_to(REPOSITORY_ROOT).as_posix(), path.read_text(
                    encoding="utf-8"
                )


class FixtureHygieneTests(unittest.TestCase):
    def test_all_package_fixtures_are_demonstrably_synthetic(self):
        package_root = files("claude_code_data_kit").joinpath("_fixtures")
        resources = [
            item
            for item in package_root.iterdir()
            if item.name.endswith((".json", ".jsonl"))
        ]
        self.assertGreaterEqual(len(resources), 5)
        for item in resources:
            text = item.read_text(encoding="utf-8")
            self.assertIn("synthetic", text.lower(), item.name)
            self.assertEqual(find_violations(text), (), item.name)

    def test_fixture_names_do_not_claim_real_capture_origin(self):
        root = files("claude_code_data_kit").joinpath("_fixtures")
        names = [item.name.lower() for item in root.iterdir()]
        for marker in ("real", "prod", "private", "capture", "export"):
            self.assertFalse(
                any(marker in name for name in names),
                f"fixture filename contains forbidden origin marker: {marker}",
            )

    def test_all_public_text_uses_generic_hygiene_rules(self):
        findings = scan_named_texts(public_texts())
        self.assertEqual(findings, ())

    def test_generic_rules_detect_fictional_bad_samples(self):
        fictional_email = "person" + "@" + "example.test"
        fictional_token = "sk" + "-" + "A" * 24
        fictional_path = "/" + "home" + "/sample-user/private.txt"
        samples = (
            fictional_email,
            fictional_token,
            fictional_path,
            FICTIONAL_SENTINELS[0],
        )
        for sample in samples:
            self.assertTrue(find_violations(sample), sample)


if __name__ == "__main__":
    unittest.main()
