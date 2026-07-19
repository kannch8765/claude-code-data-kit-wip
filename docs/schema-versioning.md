# Schema versioning

The canonical schema version is `1.0.0`. Package version and schema version are independent.

A schema major change is required for incompatible field removal, semantic reinterpretation, or invariant relaxation. Additive optional fields may use a schema minor change. Documentation-only clarifications and evidence corrections that preserve serialized field shape may use a patch change.

Collectors must reject unsupported future transcript major versions rather than guessing compatibility.
