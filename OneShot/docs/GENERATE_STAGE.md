# System Generate stage — explicit ownership boundary

Accepted logical order:

```text
Source -> Scan -> Read -> Prepare -> Systems.generate(prepared_input=...)
       -> Validate generated artifact -> Existing stored artifact
```

- The foreground Worker orchestrates source access, scanning, reading, and preparation.
- `Systems.generate` accepts only `PreparedInput`, refuses a failed readiness gate,
  delegates to the existing `AutoGenerator.run`, and validates the produced artifact.
- The HTTP `POST /api/conversations/{cid}/jobs` route **admits** a complete System job.
  The Worker executes the complete workflow after admission. No `POST /generate`
  endpoint is added; no generation stage may secretly rescan or re-prepare sources.
- The existing Worker is synchronous. The named stage is synchronous as well. The
  example `await Systems.generate(...)` is a target call shape, not proof that a
  synchronous execution boundary can be made async without a justified refactor.
- In evidence mode the artifact is an evidence packet, **not** a generated semantic
  answer. In model mode the provider output is separately validated against
  `GeneratedDocument` before `GeneratedArtifact` validation.
- **Unresolved product/physical discrepancy**: this candidate persists artifacts
  (`kind`, `content`, `provider`, `limitations`, source scope) rather than a physical
  `output.json`. The user specifies `output.json` as the final output; the exact
  output contract and consumer must be reconciled before changing stored artifact
  shape or introducing a new HTTP endpoint. Existing `GeneratedDocument` has
  `document` and `source_ids_used`; this is not a declaration of `OneShotOutput`.
- The background evaluator consumes terminal execution evidence and never calls
  `Systems.generate` or mutates the active workflow.
