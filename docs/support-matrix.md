# Support matrix

| Surface | Supported behavior | Version policy |
|---|---|---|
| Hooks | Lifecycle events, Agent intent/local resolved model, usage metadata | Local resolved field `>=2.1.174,<3.0.0` |
| OTel | API request usage and client-visible model attributes | Attribute aliases remain local/version-sensitive |
| Main status line | Model, documented repository/PR paths, context, limits, permission, agent name, session cost | Documented paths; no serving attestation |
| Subagent status line | Task snapshots and gated model/context fields | Model/context `>=2.1.205,<3.0.0` |
| Transcript JSONL | Message metadata, usage, response-reported model | Major version 2 only; unknown/future majors rejected |
| Lab | Managed isolated roots and package-owned synthetic check | Exact semantic version required |

Python 3.10 through 3.14 is tested in CI. Runtime dependencies are empty.
