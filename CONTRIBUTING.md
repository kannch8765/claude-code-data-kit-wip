# Contributing

Use Python 3.10 or newer. Keep runtime dependencies empty, raw conversational and tool content outside the package, fixture data demonstrably synthetic, and all public imports explicitly allowlisted.

## Branch and pull-request flow

1. Start a feature branch in the public development fork from the current official public upstream baseline.
2. Keep the diff inside the task's changed-path allowlist.
3. Sanitize implementation notes, fixtures, tests, commit messages, and branch history before publishing the branch.
4. Push the feature branch to the public development fork.
5. Open a **Draft PR** from that branch to the official public upstream.
6. Keep the PR in Draft while CI or review findings remain unresolved.
7. Address review on the same feature branch. Rewrite branch history when sensitive material entered earlier commits; a deletion commit is not sufficient.
8. Mark ready only after required CI and review gates pass. Do not publish, tag, release, or update downstream consumers as part of a core implementation PR.

## Sanitization requirements

Public changes must use repository role names rather than real account, owner, repository, host, machine, or private commit identities. Public tests may use only fictional sentinels; real denylists belong in private release checks.

A private failure must be reduced to a minimal sanitized fixture plus a regression test. Never publish real prompts, responses, thinking, tool payloads, transcripts, credentials, tokens, user identity, repository identity, absolute personal paths, or private provider endpoints.

Before review, inspect both the complete feature-branch history and the final tree. If sensitive material ever entered the branch, recreate or squash the branch from its clean upstream base and force-push the sanitized history.

## Collector evidence

Collector changes must identify the source path, semantics, source version, and evidence level. Compatibility aliases and locally observed fields may not be promoted to `official-supported` without documentation establishing both the path and semantics. Requested, resolved, status-line, response-reported, and usage-reported model labels are never backend serving attestation.

## Required local checks

```bash
python -m compileall -q src tests
python -m unittest discover -s tests -v
python -m pip install --upgrade build
python -m build
python tests/distribution_audit.py dist/*.whl dist/*.tar.gz
git diff --check
```

Install the built wheel into a clean environment and exercise the public imports plus every offline CLI path. Network-requiring lab commands must remain disabled unless the caller explicitly supplies `--allow-network`.
