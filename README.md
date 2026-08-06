# Claude Code Data Kit

> Dario doesn't know he's been instrumented.

A privacy-first, dependency-free Python package for collecting and normalizing Claude Code metadata into canonical records. It extracts a reusable normalization core while deliberately excluding downstream runtime topology, tmux integration, raw content retention, authenticated calls, and provider serving-model claims.

## Install and import

```bash
python -m pip install dist/claude_code_data_kit-0.1.0-py3-none-any.whl
python -c "import claude_code_data_kit; print(claude_code_data_kit.SCHEMA_VERSION)"
```

Supported public modules are `claude_code_data_kit`, `.collectors`, `.records`, `.dedupe`, `.routing`, `.versioning`, `.store`, `.transcript_ingest`, and `.lab`. Public names are explicitly allowlisted with `__all__`.

The stable top-level convenience API includes canonical record types, `CanonicalRecord`, `stable_id`, `record_to_dict`, `dedupe_usage`, `DarioSeizer`, and `RoutingAccumulator`. Collector adapters and lab helpers remain namespaced and are not silently promoted into the top-level surface.

## Incremental transcript ingestion

Install the package, then ingest one transcript JSONL file or a directory such as the default Claude Code project root:

```bash
claude-code-data-kit ingest-transcripts ~/.claude/projects --json
```

The command recursively reads `*.jsonl` files, sends each complete line through the existing transcript adapter, and appends privacy-preserving canonical records to `records.jsonl`. Raw prompt text, assistant text, thinking text, and tool payloads are not stored. A partial final line remains uncommitted until it is completed.

The store follows `XDG_DATA_HOME` and otherwise uses `~/.local/share/claude-code-data-kit/`. Override it with `--data-dir` or `CLAUDE_CODE_DATA_KIT_DATA_DIR`. The CLI normally obtains the local Claude Code version from `claude --version`; isolated runs can pass `--source-version 2.1.220` or set `CLAUDE_CODE_DATA_KIT_SOURCE_VERSION`.

`state.json` tracks device/inode source identity, generation, committed byte offset, line count, and compact boundary fingerprints. Records are fsynced before the state cursor is atomically replaced, and record IDs suppress duplicates when a completed append is replayed after a state-write failure. Run one ingest process per data directory; concurrent writers are not coordinated in v0.1.0.

## Isolated lab CLI

The lab uses an exact Claude Code version and a managed isolated root.

```bash
claude-code-data-kit-lab --root ./synthetic-lab --version 2.1.214 prepare
claude-code-data-kit-lab --root ./synthetic-lab --version 2.1.214 version
claude-code-data-kit-lab --root ./synthetic-lab --version 2.1.214 help
claude-code-data-kit-lab --root ./synthetic-lab --version 2.1.214 synthetic-check
```

`synthetic-check` is offline and reads sanitized fixtures installed inside the wheel. `install` and `unauthenticated-probe` require an explicit `--allow-network` flag; without it they fail before any network operation.

```bash
claude-code-data-kit-lab --root ./synthetic-lab --version 2.1.214 install --allow-network
claude-code-data-kit-lab --root ./synthetic-lab --version 2.1.214 unauthenticated-probe --allow-network
```

## Evidence boundary

Requested, client-resolved, status-line, response-reported, usage-reported, and locally observed subagent model labels are evidence about client-visible fields. None is backend serving attestation. `ModelObservationRecord.serving_model`, `RoutingAssessment.serving_model`, and `RoutingAssessment.backend_attestation_available` are constructor-protected.

Agent `PostToolUse.tool_response.resolvedModel` is retained only as a version-sensitive, unverified local implementation field for the observed 2.x boundary. It is not official-supported or authoritative.

## Maintenance source of truth

The official public upstream is the sole formal source of the core. Changes move through a public development fork and Draft PR, then through an approved release before any downstream PWA consumer updates an exact dependency pin. Private experimentation and downstream consumers do not retain parallel copies of the core.

## License

Claude Code Data Kit is licensed under the MIT License. See `LICENSE`.

## Release status

Version `0.1.0` remains unreleased. MIT licensing has been selected and recorded, but no tag, GitHub Release, or package publication has been created.
