# Evaluation reference material

`inventory.md` and `fixture.md` are the two Toloka reference documents received on 2026-10-12. They are preserved verbatim in this folder. They describe candidate evaluation inputs, not installed test cases, product decisions, or signed real-model evidence.

Use `inventory.md` as a historical gap map. Its archive counts (167 manifest entries and 170 archive members) do not match this installed export: the current SHA256SUMS file has 174 entries, covering the tarball and 173 packaged source files. Recheck every claimed missing case against the current source before implementation.

Use `fixture.md` as a candidate input catalog for P09, P11, P12, and I05. The P11 semantic evaluator, scoring policy, evidence schema, and gate placement remain open in `../P11_SEMANTIC_DECISION.md`. Real-model and vision acceptance require their documented runtime, credentials, reference material, and approval. Do not copy these reference inputs into `data/realmodel_evidence` or mark them as passing acceptance evidence.
