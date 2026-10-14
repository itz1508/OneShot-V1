# v5 Phase 0 — Repository reconciliation (2026-10-11T19:00Z)

## State inspected

- v4 git_sha `6cd49b6eaaffee4311673d2ffa1136c1f131e412`
- SQLite user_version = 5
- Existing tables: conversations, messages, sources, source_links, jobs, runs,
  artifacts, events, drafts, draft_revisions, apply_intents, applied,
  background_evaluations

## Existing "prompt" is a message

`jobs.prompt_message_id` references `messages(id, channel='system')`. Once a job
is admitted the reference is immutable. There is NO version tree,
draft/published distinction, variable layer, or restoration primitive.

## Gap analysis per spec

| Feature | Status in v4 | v5 action |
|---|---|---|
| A Workspace | Absent | Build (Phase 1 + Phase 8) |
| B Immutable versions | Absent | Build (Phase 2) |
| C Restore | Absent | Build (Phase 5) |
| D Variables | Absent | Build (Phase 3) with approved `${name}` syntax |
| E Freeze on admission | Partial (job rows freeze prompt_message_id) | Extend to prompt_version_id (Phase 2+4) |
| F System-owned execution | Present via `POST /jobs` | **Extend** per §16; do NOT add `/system/run` |
| G Compare | Absent | Build (Phase 5) |
| H Evaluate | Absent | Build (Phase 6) |
| I Optimize | Absent | Build (Phase 7) — local llama.cpp first per operator decision |
| J Run History | Present (v4) | Extend `list_jobs` to surface prompt_version_id |
| K Events | Present | Reuse existing event table; add `prompt_*` kinds |
| L Apply boundary | Present | **Must not be broken** |

## Schema plan (SQLite user_version 5 → 6)

```
CREATE TABLE prompt_assets(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(conversation_id, name)
);
CREATE TABLE prompt_versions(
  id TEXT PRIMARY KEY,
  prompt_asset_id TEXT NOT NULL REFERENCES prompt_assets(id),
  version_number INTEGER NOT NULL,
  content TEXT NOT NULL,
  variables_json TEXT NOT NULL,
  content_sha256 TEXT NOT NULL,
  published_at TEXT NOT NULL,
  restored_from TEXT REFERENCES prompt_versions(id),
  UNIQUE(prompt_asset_id, version_number)
);
CREATE TABLE prompt_drafts(
  id TEXT PRIMARY KEY,
  prompt_asset_id TEXT NOT NULL REFERENCES prompt_assets(id) UNIQUE,
  revision INTEGER NOT NULL,
  content TEXT NOT NULL,
  variables_json TEXT NOT NULL,
  base_version_id TEXT REFERENCES prompt_versions(id),
  updated_at TEXT NOT NULL
);
CREATE TABLE prompt_evaluations(
  id TEXT PRIMARY KEY,
  prompt_version_id TEXT NOT NULL REFERENCES prompt_versions(id),
  job_id TEXT REFERENCES jobs(id),
  status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
  criteria_json TEXT NOT NULL,
  findings_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE prompt_optimizations(
  id TEXT PRIMARY KEY,
  prompt_asset_id TEXT NOT NULL REFERENCES prompt_assets(id),
  base_version_id TEXT REFERENCES prompt_versions(id),
  base_draft_revision INTEGER,
  provider TEXT NOT NULL,
  model TEXT,
  proposed_content TEXT NOT NULL,
  rationale TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN ('proposed','accepted','rejected')),
  created_at TEXT NOT NULL
);
ALTER TABLE jobs ADD COLUMN prompt_version_id TEXT REFERENCES prompt_versions(id);
ALTER TABLE jobs ADD COLUMN resolved_variables_json TEXT;
```

## Variable syntax rules (operator-approved)

- Only `${name}` interpolates (name = `[A-Za-z_][A-Za-z0-9_]*`).
- `$$` escapes to literal `$`.
- Every reference MUST appear in `variables_json` (declared).
- Undeclared reference OR missing value => 422, resolution rejected.
- Resolution is one-pass; supplied values are NEVER re-interpolated.
- Resolved template + variables are frozen onto `jobs.resolved_variables_json`.

## Provider rules (operator-approved)

- Optimizer calls `systems.model_transport.request_text` with existing
  `system_connection(cfg)`.
- Local llama.cpp loopback is the default (ADR-002 unchanged).
- If `cfg.provider == 'evidence'`, optimization gate is `OPTIMIZER_PROVIDER_UNDECIDED`.
- No automatic hosted fallback; errors propagate.

## Non-goals (per spec §22)

- NO new workflow controller.
- NO `/system/run` or `/prompts/{id}/execute` route.
- NO modification to Apply boundary.
- NO auto-publish from evaluation or optimization.
