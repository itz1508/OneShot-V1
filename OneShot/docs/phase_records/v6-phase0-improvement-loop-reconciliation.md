# v6 Phase 0 — Improvement loop reconciliation (2026-10-12T01:30Z)

Baseline: v5.4 git `6754b320` extracted from
`oneshot-complete-release-2026-10-12-v5.4.tar.gz`
(SHA-256 `5a5f89c0ab87afcdc4a15fa611ea024851fa82ee9b6fd0ac5dd5391c4bdcdf07`).
Reproduced on this host: 219 pytest passed.

## Mapping cookbook concepts → OneShot responsibilities

| Cookbook concept | OneShot owner (file / module) | Status |
|---|---|---|
| Agent | System operation + `Worker.execute` in `systems/operations.py` | present |
| Agent Runner | `admit` + `Worker.step` in `systems/operations.py` | present |
| Agent Instructions | `prompt_versions` (`systems/prompts.py`) + prompt-message channel | present (v5) |
| Agent Configuration | `systems/settings.py`, `jobs.scope_json`, `jobs.resolved_variables_json` | present |
| Agent Harness | Scanner → Advisor → Quality → Generator pipeline in `Worker.execute` | present |
| Agent Tool | capabilities in `capabilities/*` | present |
| Agent Trace | `events`, `runs`, `artifacts`, `jobs` tables + `events_replay_idx` | present |
| Human Feedback | **absent** | **GAP (Phase 2)** |
| LLM Feedback | **absent** | **GAP (Phase 4, optional)** |
| Promptfoo Eval | `prompt_evaluations` (structural, prompt-only) | partial (Phase 3 adds job-level) |
| HALO Optimization | `prompt_optimizations` (advisory, no auto-publish) | present (v5) |
| Codex Handoff | **absent** | **GAP (Phase 5, text artefact)** |
| Agent Improvement | **absent** | **GAP (Phases 2-6)** |
| Agent Deployment | `apply_intents` + `applied` tables (unchanged) | present, boundary preserved |

## Protected invariants that must survive this feature

- `jobs.status` enum stays `queued / running / completed / blocked / failed`.
- `events` is append-only; no new write path mutates persisted events.
- `apply_intents`/`applied` boundary stays explicit — Phase 11 directive §14.
- Prompt publishing stays explicit (v5 Phase 7 contract).
- Deterministic Background in `systems/background.py` is **preserved**, not replaced.
- Semantic quality remains `not_evaluated`; a model finding never becomes a human label.
- All optional provider work routes through `systems/model_transport.py`.

## Schema plan (SQLite user_version 6 → 7)

```
CREATE TABLE job_reviews(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  job_id TEXT NOT NULL REFERENCES jobs(id),
  revision INTEGER NOT NULL DEFAULT 1,
  decision TEXT NOT NULL CHECK(decision IN
    ('observed_defect','reviewer_expectation','potential_defect','unresolved_decision')),
  required TEXT NOT NULL DEFAULT '',        -- required observed behaviour
  prohibited TEXT NOT NULL DEFAULT '',      -- prohibited unsupported behaviour
  reason TEXT NOT NULL DEFAULT '',
  limitations TEXT NOT NULL DEFAULT '',
  evidence_source_ids TEXT NOT NULL DEFAULT '[]',  -- JSON array of source ids
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(job_id)                             -- one review per job; revisions carry forward
);
CREATE INDEX job_reviews_conv_idx ON job_reviews(conversation_id, created_at);

CREATE TABLE job_evaluations(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  job_id TEXT NOT NULL REFERENCES jobs(id),
  review_id TEXT REFERENCES job_reviews(id),
  status TEXT NOT NULL CHECK(status IN
    ('proposed','approved','rejected','running','completed','failed')),
  criteria_json TEXT NOT NULL,       -- same schema as prompt_evaluations.criteria_json
  findings_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE improvement_proposals(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  issue_summary TEXT NOT NULL,
  affected_responsibility TEXT NOT NULL,
  current_behavior TEXT NOT NULL DEFAULT '',
  required_behavior TEXT NOT NULL DEFAULT '',
  proposed_correction TEXT NOT NULL DEFAULT '',
  risks TEXT NOT NULL DEFAULT '',
  evidence_json TEXT NOT NULL DEFAULT '{}',   -- {job_ids:[], review_ids:[], issue_codes:[]}
  status TEXT NOT NULL CHECK(status IN
    ('proposed','accepted','rejected','implemented')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

## Non-goals (directive §16, §21)

- No `openai-agents` SDK, no HALO, no Promptfoo runtime dependency.
- No autonomous code mutation.
- No cross-conversation leakage.
- No automatic publication / Apply from improvement loop.
- No new workflow controller — the loop is a **read + persist** overlay on committed evidence.
