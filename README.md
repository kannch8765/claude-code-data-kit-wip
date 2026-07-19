# Claude Code Data Kit

> Dario doesn't know he's been instrumented.

A privacy-first, dependency-free Python package for collecting and normalizing Claude Code metadata into canonical records. It extracts a reusable normalization core while deliberately excluding downstream runtime topology, tmux integration, raw content retention, authenticated calls, and provider serving-model claims.

## Install and import

```bash
python -m pip install dist/claude_code_data_kit-0.1.0-py3-none-any.whl
python -c "import claude_code_data_kit; print(claude_code_data_kit.SCHEMA_VERSION)"
```

Supported public modules are `claude_code_data_kit`, `.collectors`, `.records`, `.dedupe`, `.routing`, `.versioning`, and `.lab`. Public names are explicitly allowlisted with `__all__`.

The stable top-level convenience API includes canonical record types, `CanonicalRecord`, `stable_id`, `record_to_dict`, `dedupe_usage`, `DarioSeizer`, and `RoutingAccumulator`. Collector adapters and lab helpers remain namespaced and are not silently promoted into the top-level surface.

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

## Release status

Version `0.1.0` is an unreleased package bootstrap. Publication and release creation are blocked pending an explicit maintainer license decision. No license metadata is set.
