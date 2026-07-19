# Private-to-public maintenance railway

The official public upstream is the single formal source of truth for the reusable Claude Code normalization core: canonical records, collectors, deduplication, routing evidence, version gates, lab isolation, sanitized fixtures, and contracts.

The maintenance railway is:

```text
private experimental repository
  → public development fork
  → official public upstream
  → tagged release
  → downstream PWA consumer exact pin
```

## Repository roles

- The **private experimental repository** may contain experiments, local observations, and private failure evidence. It must not become a long-lived second implementation of the core.
- The **public development fork** is the sanitization and review staging area. Work happens on a feature branch created from the official upstream baseline.
- The **official public upstream** is the only formal core source. Accepted fixes and contracts live there.
- A **tagged release** is created only after upstream merge, release approval, and an explicit maintainer license decision.
- The **downstream PWA consumer** depends on an exact released version. It does not retain an embedded second copy of the core.

## Change flow

1. Reproduce a private bug without copying private payloads into public work.
2. Reduce the bug to a minimal sanitized fixture and a regression test.
3. Implement the fix on a feature branch in the public development fork.
4. Audit the complete branch tree and history for identities, credentials, endpoints, absolute paths, and private artifacts.
5. Run unit, contract, fixture-hygiene, build, wheel, sdist, and installed-wheel checks.
6. Open a Draft PR from the public development fork feature branch to the official public upstream.
7. Complete CI and review before the PR is marked ready or merged.
8. After upstream merge, create an approved tag/release.
9. Only then update the downstream PWA consumer with an exact dependency pin.

A private bug is not considered transferred until it has both a sanitized public fixture and a regression test. The private experimental repository must not maintain a divergent copy after the public fix is accepted.

## Downstream update and rollback

The downstream PWA consumer must not store a second source copy of the core. A downstream update is an exact dependency bump to an upstream release.

Rollback is performed by reverting the dependency-bump commit or pinning the previous approved release. Rollback must never reintroduce an embedded fork or allow two core implementations to coexist.

## Public extraction boundary

Public extraction records use repository role names rather than account, owner, repository, machine, or private commit identities. Approved frozen references and any real denylist remain in private release tooling and are not copied into public documentation or tests.

PWA/runtime topology, tmux code, credentials, raw conversational content, private endpoints, and private fixtures are not part of this package. Release remains blocked until maintainers explicitly choose a software license.
