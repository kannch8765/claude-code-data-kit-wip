# Evidence boundaries

The Data Kit normalizes structured client-visible evidence; it does not attest which model a provider backend served.

| Evidence | Classification | Boundary |
|---|---|---|
| Documented hook/status-line field with identified path and semantics | `official-supported` or documented version-sensitive | Source documentation and declared version boundary |
| Compatibility alias or locally observed OTel/transcript field | `local-implementation-detail` | Observed versions only |
| Agent `PostToolUse.tool_response.resolvedModel` | `local-implementation-detail` | `>=2.1.174,<3.0.0`; unverified local field |
| Requested/resolved/status-line/response/usage model label | Client-visible evidence only | Never backend serving attestation |

`tool_response.resolvedModel` must not be described as official, authoritative, or backend serving identity. A collector warning accompanies the field. Constructor invariants prevent serving-model or backend-attestation population.
