from __future__ import annotations

import test_bootstrap
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from claude_code_data_kit._lab_cli import main as lab_cli_main
from claude_code_data_kit.lab import ClaudeLabRunner, ClaudeLabSpec, LabCommandResult, synthetic_check
from claude_code_data_kit.records import VersionBoundary
from claude_code_data_kit.versioning import SemVer, version_allows


class VersionLabTests(unittest.TestCase):
    def test_semver_and_version_gates(self):
        self.assertEqual(SemVer.parse("v2.1.214").patch, 214)
        boundary = VersionBoundary("2.1.205", "3.0.0")
        self.assertTrue(version_allows("2.1.214", boundary))
        self.assertFalse(version_allows("2.1.204", boundary))
        self.assertFalse(version_allows("3.0.0", boundary))
        self.assertFalse(version_allows(None, boundary))

    def test_isolated_root_and_repeatability(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lab"
            spec = ClaudeLabSpec(root, "2.1.214")
            first = synthetic_check(spec)
            second = synthetic_check(spec)
            self.assertEqual(first, second)
            self.assertTrue((root / ".claude-code-data-kit-lab").exists())
            self.assertFalse((root / (".claude-" + "observability-lab")).exists())
            self.assertEqual(first["fixture_source"], "package-resource")
            self.assertEqual(first["schema_version"], "1.0.0")

    def test_runner_reuses_managed_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = ClaudeLabSpec(Path(tmp) / "lab", "2.1.214")
            runner = ClaudeLabRunner(spec)
            spec.prepare()
            spec.prepare()
            command = ("true",) if os.name != "nt" else ("cmd", "/c", "exit", "0")
            first = runner.run(command)
            second = runner.run(command)
            self.assertEqual(first.returncode, 0)
            self.assertEqual(second.returncode, 0)
            self.assertEqual(first.stdout_bytes, 0)

    def test_unmanaged_and_dangerous_roots_are_rejected(self):
        with self.assertRaises(ValueError):
            ClaudeLabSpec(Path("/"), "2.1.214").validate()
        with self.assertRaises(ValueError):
            ClaudeLabSpec(Path.home().parent, "2.1.214").validate()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lab"
            root.mkdir()
            (root / "unmanaged").write_text("synthetic", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unmanaged"):
                ClaudeLabSpec(root, "2.1.214").validate()

    def test_environment_strips_credentials_endpoints_and_proxies(self):
        with tempfile.TemporaryDirectory() as tmp:
            spec = ClaudeLabSpec(Path(tmp) / "lab", "2.1.214")
            env = spec.environment(
                {
                    "PATH": "/synthetic/bin",
                    "LANG": "C",
                    "ANTHROPIC_API_KEY": "secret",
                    "CLAUDE_CODE_OAUTH_TOKEN": "secret",
                    "ANTHROPIC_BASE_URL": "synthetic-provider-endpoint",
                    "HTTP_PROXY": "synthetic-proxy",
                    "MINIMAX_API_KEY": "secret",
                }
            )
            for key in (
                "ANTHROPIC_API_KEY",
                "CLAUDE_CODE_OAUTH_TOKEN",
                "ANTHROPIC_BASE_URL",
                "HTTP_PROXY",
                "MINIMAX_API_KEY",
            ):
                self.assertNotIn(key, env)
            self.assertEqual(env["HOME"], str(spec.home_dir))
            self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(spec.config_dir))
            self.assertEqual(env["OTEL_TRACES_EXPORTER"], "none")
            self.assertEqual(env["OTEL_METRICS_EXPORTER"], "none")
            self.assertEqual(env["OTEL_LOGS_EXPORTER"], "none")
            self.assertEqual(env["OTEL_LOG_USER_PROMPTS"], "0")
            self.assertEqual(env["CLAUDE_CODE_ENABLE_ENHANCED_TRACING"], "0")
            self.assertEqual(
                spec.install_command()[-1],
                "@anthropic-ai/claude-code@2.1.214",
            )

    def test_network_operations_are_explicitly_disabled_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = ClaudeLabRunner(ClaudeLabSpec(Path(tmp) / "lab", "2.1.214"))
            with self.assertRaises(PermissionError):
                runner.install()
            with self.assertRaises(PermissionError):
                runner.probe_unauthenticated_error_path()

    def test_exact_version_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ClaudeLabSpec(Path(tmp) / "lab", "latest").validate()


    def test_cli_prepare_version_and_help_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lab"
            prepare_output = StringIO()
            with redirect_stdout(prepare_output):
                self.assertEqual(
                    lab_cli_main(
                        [
                            "--root",
                            str(root),
                            "--version",
                            "2.1.214",
                            "prepare",
                        ]
                    ),
                    0,
                )
            self.assertTrue(json.loads(prepare_output.getvalue())["managed"])
            binary = root / "npm" / "bin" / "claude"
            binary.parent.mkdir(parents=True, exist_ok=True)
            binary.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"--version\" ]; then echo 2.1.214; else echo synthetic-help; fi\n",
                encoding="utf-8",
            )
            binary.chmod(0o755)
            for command in ("version", "help"):
                output = StringIO()
                with redirect_stdout(output):
                    result = lab_cli_main(
                        [
                            "--root",
                            str(root),
                            "--version",
                            "2.1.214",
                            command,
                        ]
                    )
                self.assertEqual(result, 0)
                self.assertEqual(json.loads(output.getvalue())["returncode"], 0)

    def test_cli_network_commands_require_explicit_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lab"
            for command in ("install", "unauthenticated-probe"):
                error = StringIO()
                with redirect_stderr(error):
                    result = lab_cli_main(
                        [
                            "--root",
                            str(root),
                            "--version",
                            "2.1.214",
                            command,
                        ]
                    )
                self.assertEqual(result, 2)
                self.assertIn("explicit", error.getvalue())

    def test_cli_network_flags_are_forwarded(self):
        synthetic_result = LabCommandResult(
            command=("synthetic-command",),
            returncode=0,
            stdout_sha256="0" * 64,
            stderr_sha256="0" * 64,
            stdout_bytes=0,
            stderr_bytes=0,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lab"
            cases = (
                ("install", "install"),
                ("unauthenticated-probe", "probe_unauthenticated_error_path"),
            )
            for command, method in cases:
                output = StringIO()
                with patch.object(
                    ClaudeLabRunner, method, return_value=synthetic_result
                ) as mocked, redirect_stdout(output):
                    result = lab_cli_main(
                        [
                            "--root",
                            str(root),
                            "--version",
                            "2.1.214",
                            command,
                            "--allow-network",
                        ]
                    )
                self.assertEqual(result, 0)
                mocked.assert_called_once_with(allow_network=True)
                self.assertEqual(json.loads(output.getvalue())["returncode"], 0)

    def test_cli_synthetic_check_uses_package_resources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "lab"
            result = lab_cli_main(
                [
                    "--root",
                    str(root),
                    "--version",
                    "2.1.214",
                    "synthetic-check",
                ]
            )
            self.assertEqual(result, 0)
            self.assertTrue((root / "fixtures" / "synthetic-check.json").exists())


if __name__ == "__main__":
    unittest.main()
