from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from claude_code_data_kit import cli
from claude_code_data_kit.store import CanonicalRecordStore, resolve_data_dir
from claude_code_data_kit.transcript_ingest import TranscriptIngestor


SOURCE_VERSION = "2.1.220"


def _line(
    *,
    kind: str = "user",
    session: str = "session-1",
    message_id: str = "message-1",
    content="private text",
    timestamp: str | None = "2026-08-05T00:00:00Z",
) -> bytes:
    payload = {
        "type": kind,
        "sessionId": session,
        "message": {
            "id": message_id,
            "role": kind,
            "content": content,
        },
    }
    if timestamp is not None:
        payload["timestamp"] = timestamp
    if kind == "assistant":
        payload["message"]["model"] = "claude-opus-4-6"
        payload["message"]["usage"] = {
            "input_tokens": 10,
            "output_tokens": 4,
        }
    return json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"


def _records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _state(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _entry_for_path(state: dict[str, object], path: Path) -> dict[str, object]:
    absolute = str(path.resolve())
    sources = state["sources"]
    assert isinstance(sources, dict)
    for entry in sources.values():
        assert isinstance(entry, dict)
        if entry["path"] == absolute:
            return entry
    raise AssertionError(f"missing state entry for {absolute}")


class TranscriptIngestTests(unittest.TestCase):
    def test_first_ingest_creates_append_only_store_and_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(_line(content="first private prompt"))
            data_dir = root / "data"

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)

            self.assertEqual(summary.files_seen, 1)
            self.assertEqual(summary.files_changed, 1)
            self.assertEqual(summary.records_parsed, 1)
            self.assertEqual(summary.records_appended, 1)
            self.assertEqual(summary.files_failed, 0)
            records = _records(data_dir / "records.jsonl")
            self.assertEqual(records[0]["kind"], "message")
            self.assertEqual(records[0]["schema_version"], "1.0.0")
            self.assertTrue(str(records[0]["record_id"]).startswith("message_"))
            self.assertEqual(records[0]["role"], "user")
            state = _state(data_dir / "state.json")
            entry = _entry_for_path(state, transcript)
            self.assertEqual(entry["offset"], transcript.stat().st_size)
            self.assertEqual(entry["line_number"], 1)
            self.assertIn("source_id", entry)
            self.assertEqual(state["schema_version"], "1.0.0")
            self.assertIn("last_successful_ingest_at", state)

    def test_repeat_without_changes_does_not_append_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(_line())
            data_dir = root / "data"
            ingestor = TranscriptIngestor(source_version=SOURCE_VERSION, data_dir=data_dir)

            first = ingestor.ingest(transcript)
            second = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)

            self.assertEqual(first.records_appended, 1)
            self.assertEqual(second.records_appended, 0)
            self.assertEqual(second.records_parsed, 0)
            self.assertEqual(len(_records(data_dir / "records.jsonl")), 1)

    def test_append_only_reads_new_complete_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(_line(message_id="one"))
            data_dir = root / "data"
            TranscriptIngestor(source_version=SOURCE_VERSION, data_dir=data_dir).ingest(transcript)
            with transcript.open("ab") as handle:
                handle.write(_line(message_id="two"))

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)

            self.assertEqual(summary.records_parsed, 1)
            self.assertEqual(summary.records_appended, 1)
            self.assertEqual(len(_records(data_dir / "records.jsonl")), 2)

    def test_partial_tail_does_not_advance_and_is_ingested_after_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            first = _line(message_id="one")
            second = _line(message_id="two")
            split = len(second) // 2
            transcript.write_bytes(first + second[:split])
            data_dir = root / "data"

            first_summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)
            first_state = _state(data_dir / "state.json")
            self.assertEqual(_entry_for_path(first_state, transcript)["offset"], len(first))
            self.assertEqual(first_summary.records_appended, 1)

            with transcript.open("ab") as handle:
                handle.write(second[split:])
            second_summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)

            self.assertEqual(second_summary.records_appended, 1)
            second_state = _state(data_dir / "state.json")
            self.assertEqual(
                _entry_for_path(second_state, transcript)["offset"],
                transcript.stat().st_size,
            )

    def test_malformed_line_stops_cursor_and_other_file_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            bad = inputs / "bad.jsonl"
            good = inputs / "good.jsonl"
            valid_prefix = _line(message_id="before")
            bad.write_bytes(valid_prefix + b'{"type":"user" BROKEN}\n' + _line(message_id="after"))
            good.write_bytes(_line(message_id="good"))
            data_dir = root / "data"

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(inputs)

            self.assertEqual(summary.files_failed, 1)
            self.assertEqual(summary.records_appended, 2)
            self.assertEqual(summary.errors[0].reason, "malformed_json")
            self.assertNotIn("BROKEN", json.dumps(summary.to_dict()))
            state = _state(data_dir / "state.json")
            self.assertEqual(_entry_for_path(state, bad)["offset"], len(valid_prefix))
            self.assertEqual(_entry_for_path(state, good)["offset"], good.stat().st_size)

    def test_multiple_files_keep_independent_cursors(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            first = inputs / "first.jsonl"
            second = inputs / "nested" / "second.jsonl"
            second.parent.mkdir()
            first.write_bytes(_line(message_id="first"))
            second.write_bytes(_line(message_id="second"))
            data_dir = root / "data"

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(inputs)

            self.assertEqual(summary.files_seen, 2)
            self.assertEqual(summary.records_appended, 2)
            state = _state(data_dir / "state.json")
            self.assertEqual(_entry_for_path(state, first)["offset"], first.stat().st_size)
            self.assertEqual(_entry_for_path(state, second)["offset"], second.stat().st_size)

    def test_truncate_resets_generation_and_ingests_new_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(_line(message_id="one") + _line(message_id="two"))
            data_dir = root / "data"
            TranscriptIngestor(source_version=SOURCE_VERSION, data_dir=data_dir).ingest(transcript)
            inode_before = transcript.stat().st_ino
            transcript.write_bytes(_line(message_id="new"))
            self.assertEqual(transcript.stat().st_ino, inode_before)

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)

            self.assertEqual(summary.records_appended, 1)
            self.assertEqual(len(_records(data_dir / "records.jsonl")), 3)
            state = _state(data_dir / "state.json")
            self.assertEqual(_entry_for_path(state, transcript)["generation"], 1)

    def test_same_path_replacement_uses_new_source_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(_line(message_id="old"))
            data_dir = root / "data"
            TranscriptIngestor(source_version=SOURCE_VERSION, data_dir=data_dir).ingest(transcript)
            old_inode = transcript.stat().st_ino
            replacement = root / "replacement.tmp"
            replacement.write_bytes(_line(message_id="new"))
            os.replace(replacement, transcript)
            self.assertNotEqual(transcript.stat().st_ino, old_inode)

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)

            self.assertEqual(summary.records_appended, 1)
            state = _state(data_dir / "state.json")
            self.assertEqual(len(state["sources"]), 2)

    def test_rotation_does_not_reingest_renamed_old_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            current = inputs / "session.jsonl"
            current.write_bytes(_line(message_id="old"))
            data_dir = root / "data"
            TranscriptIngestor(source_version=SOURCE_VERSION, data_dir=data_dir).ingest(inputs)
            current.rename(inputs / "session.rotated.jsonl")
            current.write_bytes(_line(message_id="new"))

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(inputs)

            self.assertEqual(summary.records_appended, 1)
            self.assertEqual(len(_records(data_dir / "records.jsonl")), 2)

    def test_same_inode_same_size_rewrite_is_detected_by_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            old = _line(message_id="aaaa")
            new = _line(message_id="bbbb")
            self.assertEqual(len(old), len(new))
            transcript.write_bytes(old)
            data_dir = root / "data"
            TranscriptIngestor(source_version=SOURCE_VERSION, data_dir=data_dir).ingest(transcript)
            inode = transcript.stat().st_ino
            transcript.write_bytes(new)
            self.assertEqual(transcript.stat().st_ino, inode)

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)

            self.assertEqual(summary.records_appended, 1)
            state = _state(data_dir / "state.json")
            self.assertEqual(_entry_for_path(state, transcript)["generation"], 1)

    def test_records_append_before_state_failure_replays_without_duplicate(self) -> None:
        class SimulatedCrash(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            # Missing timestamp exercises volatile observed-at fields on replay.
            transcript.write_bytes(_line(timestamp=None))
            data_dir = root / "data"

            def crash() -> None:
                raise SimulatedCrash("after records append")

            with self.assertRaises(SimulatedCrash):
                TranscriptIngestor(
                    source_version=SOURCE_VERSION,
                    data_dir=data_dir,
                    after_records_append=crash,
                ).ingest(transcript)

            self.assertEqual(len(_records(data_dir / "records.jsonl")), 1)
            state_after_crash = _state(data_dir / "state.json")
            self.assertEqual(_entry_for_path(state_after_crash, transcript)["offset"], 0)

            replay = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(transcript)

            self.assertEqual(replay.records_parsed, 1)
            self.assertEqual(replay.records_appended, 0)
            self.assertEqual(replay.records_skipped_as_duplicate, 1)
            self.assertEqual(len(_records(data_dir / "records.jsonl")), 1)
            final_state = _state(data_dir / "state.json")
            self.assertEqual(
                _entry_for_path(final_state, transcript)["offset"],
                transcript.stat().st_size,
            )

    def test_store_never_contains_prompt_assistant_or_tool_payload_text(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            prompt_secret = "PROMPT-SECRET-7ea4"
            assistant_secret = "ASSISTANT-SECRET-a11d"
            tool_secret = "TOOL-PAYLOAD-SECRET-34f2"
            transcript.write_bytes(
                _line(message_id="user", content=prompt_secret)
                + _line(
                    kind="assistant",
                    message_id="assistant",
                    content=[
                        {"type": "text", "text": assistant_secret},
                        {
                            "type": "tool_use",
                            "name": "SyntheticTool",
                            "input": {"secret": tool_secret},
                        },
                    ],
                )
            )
            data_dir = root / "data"

            TranscriptIngestor(source_version=SOURCE_VERSION, data_dir=data_dir).ingest(transcript)

            stored = (data_dir / "records.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(prompt_secret, stored)
            self.assertNotIn(assistant_secret, stored)
            self.assertNotIn(tool_secret, stored)
            self.assertIn('"content_length"', stored)

    def test_custom_data_directory_and_environment_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(_line())
            custom = root / "custom-store"

            summary = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=custom,
            ).ingest(transcript)

            self.assertEqual(summary.store_path, str(custom / "records.jsonl"))
            self.assertTrue((custom / "state.json").exists())
            self.assertEqual(
                resolve_data_dir(environ={"CLAUDE_CODE_DATA_KIT_DATA_DIR": str(custom)}),
                custom,
            )
            xdg = root / "xdg"
            self.assertEqual(
                resolve_data_dir(environ={"XDG_DATA_HOME": str(xdg)}),
                xdg / "claude-code-data-kit",
            )

    def test_cli_json_summary_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(_line())
            data_dir = root / "data"
            stdout = io.StringIO()
            stderr = io.StringIO()

            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = cli.main(
                    [
                        "ingest-transcripts",
                        str(transcript),
                        "--source-version",
                        SOURCE_VERSION,
                        "--data-dir",
                        str(data_dir),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 0)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["files_seen"], 1)
            self.assertEqual(payload["records_appended"], 1)
            self.assertEqual(payload["store_path"], str(data_dir / "records.jsonl"))
            self.assertEqual(payload["state_path"], str(data_dir / "state.json"))

    def test_cli_returns_one_for_per_file_malformed_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(b"{broken}\n")
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                exit_code = cli.main(
                    [
                        "ingest-transcripts",
                        str(transcript),
                        "--source-version",
                        SOURCE_VERSION,
                        "--data-dir",
                        str(root / "data"),
                        "--json",
                    ]
                )

            self.assertEqual(exit_code, 1)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["files_failed"], 1)
            self.assertEqual(payload["errors"][0]["byte_offset"], 0)
            self.assertNotIn("broken", stdout.getvalue())

    def test_directory_ignores_unrelated_files_and_store_itself(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inputs = root / "inputs"
            inputs.mkdir()
            (inputs / "notes.txt").write_text("not a transcript", encoding="utf-8")
            transcript = inputs / "session.JSONL"
            transcript.write_bytes(_line())
            data_dir = inputs / "data"

            first = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(inputs)
            second = TranscriptIngestor(
                source_version=SOURCE_VERSION,
                data_dir=data_dir,
            ).ingest(inputs)

            self.assertEqual(first.files_seen, 1)
            self.assertEqual(second.files_seen, 1)
            self.assertEqual(second.records_appended, 0)

    def test_existing_partial_store_tail_is_repaired_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            transcript = root / "session.jsonl"
            transcript.write_bytes(_line())
            data_dir = root / "data"
            TranscriptIngestor(source_version=SOURCE_VERSION, data_dir=data_dir).ingest(transcript)
            records_path = data_dir / "records.jsonl"
            complete_size = records_path.stat().st_size
            with records_path.open("ab") as handle:
                handle.write(b'{"record_id":')

            CanonicalRecordStore(data_dir)

            self.assertEqual(records_path.stat().st_size, complete_size)
            self.assertEqual(len(_records(records_path)), 1)

    def test_source_version_can_come_from_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"CLAUDE_CODE_DATA_KIT_SOURCE_VERSION": SOURCE_VERSION},
            clear=False,
        ):
            self.assertEqual(cli._resolve_source_version(None), SOURCE_VERSION)


if __name__ == "__main__":
    unittest.main()
