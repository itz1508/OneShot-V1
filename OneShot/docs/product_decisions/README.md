# Product decisions — resolution sentinels

Each mandatory product decision in `scripts/verify_release.py::REQUIRED_PRODUCT_DECISIONS`
is signed off by writing a single JSON file here:

- Filename: `<decision-id>.resolved.json`, e.g. `P11-semantic.resolved.json`.
- Required fields:
  - `decision` — must equal the filename stem.
  - `approved_by` — operator / stakeholder identifier (non-empty string).
  - `approved_at` — RFC 3339 / ISO 8601 UTC timestamp.
  - Any additional free-form fields (`summary`, `references`, …) are accepted.

The agent does NOT create these files. They are an explicit human-in-the-loop gate.

Until every required decision carries a well-formed sentinel, `product_release_ready`
stays `false` even when every structural gate and every real-model scenario are
verified.

Open decisions:

- `P11-semantic` — see `docs/P11_SEMANTIC_DECISION.md`.
