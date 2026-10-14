# OneShot tracing

**Status:** implemented. Data lives in SQLite (`events`); projections live in `systems/operations.py:events / latest / trace`; API lives in `systems/api.py` (`GET /api/conversations/{cid}/events`, `GET /api/conversations/{cid}/events/stream`, `GET /api/conversations/{cid}/jobs/{jid}/trace`, `GET /api/conversations/{cid}/jobs/{jid}/latest`). This document pins the data model, the naming, and the content-capture policy.

## 1. Model

A **trace** is every event committed for a given job (`job_id`). A **node** is one of the fixed workflow stages (`source_access`, `scanner`, `advisor`, `auto_generator`). An **event** is one row in the `events` table.

Event row shape (SQLite table `events`):

| Column | Type | Meaning |
|---|---|---|
| `conversation_id` | TEXT | Owning conversation (per-conversation `seq` scope). |
| `seq` | INTEGER | Monotonic per-conversation sequence; used for cursor-based replay and SSE `Last-Event-ID`. |
| `job_id` | TEXT, nullable | Job this event belongs to (empty for conversation-level events). |
| `run_id` | TEXT, nullable | Specific run inside a job (reserved; usually equal to `job_id`). |
| `kind` | TEXT | Event type (see §2). |
| `node_id` | TEXT, nullable | Workflow node this event is about. |
| `edge_id` | TEXT, nullable | Workflow edge this event is about. |
| `payload_json` | TEXT | JSON object; keys follow §3. |
| `created_at` | TEXT | ISO-8601 UTC timestamp. |

The `trace()` projection groups by `job_id`, assigns each node a `status` from the latest matching kind, and computes `duration_ms` when both `node_started` and a terminal event exist. The projection does not require a schema change — all information comes from the existing `events` rows.

## 2. Event kinds (status mapping)

| Kind | Owner | `trace()` status effect |
|---|---|---|
| `conversation_created`, `agent_toggled` | API | — |
| `source_attached`, `source_detached`, `source_referenced` | `systems.operations.source_action` | — |
| `message_added` | `systems.operations.add_message` | — |
| `job_admitted` | `systems.operations.admit` | — |
| `node_started` | `systems.operations.Worker.execute` | `active`; records `started_at` |
| `node_completed` | `systems.operations.Worker.execute` | `completed`; records `ended_at` |
| `node_skipped` | `systems.operations.Worker.execute` | `skipped`; records `ended_at` |
| `node_failed` | `systems.operations.Worker.execute` | `failed`; records `ended_at` |
| `edge_observed` | `systems.operations.Worker.execute` | edge → `observed` |
| `job_completed`, `job_failed` | `systems.operations.Worker.execute` | — (job-level terminal) |
| `apply_prepared`, `apply_verified`, `apply_failed` | `systems.apply` | — |
| `background_*` | `systems.background` | — (background surface) |

## 3. Payload attribute names

Payload is a JSON object. Keys are stable; values are structured (not free text). What **may** appear:

- `source_id`, `source_ids`, `artifact_id`, `job_id`, `destination` — identifiers only.
- `action` — one of the five Source Management action literals (`INPUT_SOURCE` / `ADD_SOURCE` / `IMPORT_SOURCE` / `REFERENCE_SOURCE` / `REMOVE_SOURCE`).
- `error_code` — short canonical reason (e.g. `retry_exhausted`, `interrupted`).
- `kind` — artifact kind on `job_completed` (`evidence_packet` or `model_generated`).
- `summary` — short classifier (e.g. `verified`, `needs_review`, `interrupted`).

What **must not** appear:

- Raw source bytes or decoded text.
- Model prompts or completions, including partial tokens.
- Operator secrets, bearer tokens, cookies, CSRF values.
- User-provided file contents from attachments.
- Agent reply content.

The policy is enforced by convention at every `emit(...)` call site (grep `emit(` across `systems/`); the `systems/background.py` evaluator additionally redacts aggregated metrics before writing.

## 4. HTTP surface

| Endpoint | Shape | Notes |
|---|---|---|
| `GET /api/conversations/{cid}/events?after=&limit=&job_id=&kind=&node_id=&since=&until=` | `{events: [row, …]}` | Server-side filters are additive; defaults are backward compatible with the unfiltered form. |
| `GET /api/conversations/{cid}/events/stream` | SSE `event: activity`, 10 s keepalive | `Last-Event-ID` header is honoured; cursor-based replay. |
| `GET /api/conversations/{cid}/jobs/{jid}/trace?include_events=true` | `{job_id, nodes:[{id,status,started_at?,ended_at?,duration_ms?}], edges:[…], events:[…]}` | `duration_ms` only present when both `started_at` and a terminal timestamp exist. |
| `GET /api/conversations/{cid}/jobs/{jid}/latest` | `{latest: row \| null}` | Most recent event for the job; returns `{latest: null}` if the job has emitted none yet. |

All endpoints are auth-guarded (`Depends(auth)`). CSRF is required for state-mutating writes but not for these read endpoints.

## 5. Content-capture policy (never leaks data into traces)

The event store is kept operator-safe by construction:

1. Payloads are JSON *attribute* objects — never free-form strings holding user content.
2. All `emit(...)` call sites are in `systems/*.py`; a code review of each one is small (~20 sites) and the policy in §3 is enforceable by grep.
3. Original source bytes live in a separate content-addressed `FileStore` and are referenced from events by SHA-256 — events never carry the bytes themselves.
4. The optional background evaluator aggregates counts/codes, not content.

If a future consumer requires capturing a model prompt or completion for debugging, add it behind an explicit opt-in environment variable (name it `ONESHOT_TRACE_CONTENT_<topic>`), default to `"off"`, and restrict storage to a separate SQLite table — do not stuff it into `events.payload_json`.

## 6. Operator playbook

| Question | Answer |
|---|---|
| "What is the slowest node in job X?" | `GET /api/conversations/{cid}/jobs/{jid}/trace` → sort `nodes[].duration_ms` desc. |
| "Did my last job fail?" | `GET /api/conversations/{cid}/jobs/{jid}/latest` → inspect `kind` + `payload`. |
| "What events have node 'advisor' emitted this week?" | `GET /api/conversations/{cid}/events?node_id=advisor&since=2026-10-04T00:00:00Z&until=2026-10-11T00:00:00Z` |
| "Stream events live, resume after disconnect." | `EventSource('/api/conversations/{cid}/events/stream')` + honour `Last-Event-ID`. |
| "Snapshot everything for post-mortem." | `scripts/backup.py` writes a verified backup (SQLite + content-addressed sources). |

## 7. Known boundaries

- The `events` table is single-level per job; cross-node parent/child spans are not modelled by a `parent_seq` column. If a future consumer requires full span-tree depth, add `parent_seq INTEGER` on `events` with a migration (v3 → v4) at that time; today's `trace()` projection does not require it.
- Content filtering (§5) is a convention over `emit(...)` call sites, not an enforced schema constraint. The small call-site count keeps the invariant auditable.
- Local-only storage: there is no external telemetry sink. If needed, add an OTLP exporter behind an explicit opt-in; keep local SQLite as the authoritative record.

## 8. Response headers (every HTTP response)

Set by `systems/api.py:security_headers`:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Cache-Control: no-store`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()`
- `Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'`

Behavioural coverage for the full set lives in `tests/test_security_headers.py`.
