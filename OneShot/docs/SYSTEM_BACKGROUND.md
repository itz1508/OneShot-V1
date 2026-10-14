# OneShot System Background — Implemented candidate contract

**Scope:** Independent, system-owned, read-only post-run evaluation. This does not
implement a Pydantic Agent, a Pydantic Harness tool, a separate AI provider, or
self-authorized production learning. All work is based on committed OneShot job,
run, source, artifact and event records.

## Runtime and ownership

- The foreground `Worker` continues to own user processing. A different
  `BackgroundWorker` handles optional evaluation using a dedicated one-thread
  executor and its own asynchronous pump. Foreground API requests do not await
  background evaluation.
- The background worker **yields while any foreground job is queued or running**.
  This is a deliberately strict foreground-priority policy for the supported
  single-instance/one-Uvicorn-worker deployment. It does not prove the absence
  of all transient SQLite lock contention or quantify a production SLO.
- Set `ONESHOT_SYSTEM_BACKGROUND=false` to disable automatic background runs.
  Authorized read-only reports and previously persisted evaluations remain
  accessible. The default is enabled. Do not configure multiple Uvicorn
  workers against the same mutable single-operator workflow unless a separate
  concurrency design is reviewed and tested.
- No model, Agent, capability provider or frontend component owns routing,
  evidence quality, review, policy promotion or Apply authority.

## Durable admission, scheduling and recovery

- SQLite `PRAGMA user_version` migrates 2 -> 3 additively, preserving earlier
  tables. Versions 0/1 also migrate to 3. The new table is
  `background_evaluations` with a unique `(job_id,evaluator_version)` key.
- The background pump observes committed foreground terminal jobs and inserts
  one evaluation per `(job_id, evaluator_version)` using `INSERT OR IGNORE`
  inside a transaction. The resulting evaluation identity is stable.
- An atomic queued->running claim uses a unique ownership token and an attempt
  counter. Results are committed only while the matching token is held; stale
  workers cannot finalize a recovered evaluation. Up to three attempts are
  permitted, with coded terminal failure rather than unbounded retries.
- In the supported **single-server** restart path, incomplete `running`
  evaluations are requeued or marked retry-exhausted. Successful results are
  idempotent and never rerun under the same evaluator version.
- Evaluation input is bounded to 50 admitted source references and 10,000
  observed events. Excess event history yields a limitation, not unbounded
  content loading or false success. Stored report history is paginated (max
  100), and recurring issue analysis uses at most the last 500 completed
  evaluations per conversation.

## Trust, privacy, accuracy

- Raw original source bytes are read only for existing SHA-256 integrity
  verification. No plaintext source content, saved objective, provider output,
  secrets, or model predictions are stored in background evaluation results.
- Tombstoned/missing source records result in `skipped`; source corruption,
  missing terminal events, incomplete node transitions and artifact scope
  inconsistencies are reported as deterministic issues.
- `recorded_consistently` means only that tested provenance/trace invariants
  passed. It **never** means a generated answer was semantically accurate.
  Completed jobs are not independent correctness labels.
- Learning from historical jobs currently consists of **counting verified
  deterministic issue codes** and forming read-only proposals after at least
  two occurrences in the bounded window. Training, automatic policy changes,
  model promotion and unattended mutation are all disabled. The report says
  `training: skipped_no_independent_labels` and `model_promoted: false`.
- Background records use the same persistent SQLite lifecycle as foreground
  job evidence. There is **no newly invented retention or deletion policy**;
  a future erasure contract must address source, job and derived metadata
  together before adding selective deletion. Existing `REMOVE_SOURCE` is still
  scope detachment, not deletion. The existing `DELETE_SOURCE` action forbids
  tombstoning sources referenced by historical jobs.

## HTTP and UI

- Authenticated `GET /api/conversations/{cid}/background?limit=5` returns only
  that conversation's evaluation status, checks, coded issues, aggregate
  pattern proposals, and explicit no-training/no-promotion status. No new
  background write/mutation endpoint exists.
- Recorded events `background_queued`, `background_started`,
  `background_completed`, `background_skipped`, `background_failed` use the
  existing event table and System SSE endpoint. Events contain only stable IDs,
  actual state, and safe issue codes. No synthetic progress percentages.
- The frontend shows a separate System Background panel. `EventSource` (cookie
  authenticated) triggers read-only status refresh, using native reconnection
  and `Last-Event-ID`. A 5-second polling fallback is used only when SSE is
  absent or disconnected. The existing user-job Process Display remains
  independent and retains its original polling behavior.
- The status may show `queued`, `running`, `completed`, `skipped`, `failed` as
  **background evaluation lifecycle states**. They do not replace foreground
  job statuses, evidence quality `Sufficient / Incomplete / Unusable`, or user
  result labels `PREPARED_CONTEXT_AVAILABLE / PARTIAL_CONTEXT_WITH_GAPS /
  LIMITATION_REPORT / OUTPUT`.

## Validation

Commands from the extracted candidate root (`OneShot/`):

```bash
python -m pytest -q
cd frontend && npm ci && npm test && npm run check && npm run build && cd ..
python -m tests.e2e_http
python -m tests.e2e_browser
python -m scripts.benchmark_background --jobs 30
```

Run on the project's target Python **3.11** and Node **22+** before calling the
build production verified. A regenerated/reviewed `uv.lock` is still required
for the target environment. Docker/Compose and an actual authenticated Chromium
E2E are separate mandatory gates. The ZIP candidate has no `.git` checkout.

## Applicable authoritative references (limited scope)

- Pydantic Evals simple validation — dataset/case/evaluator practices only:
  https://pydantic.dev/docs/ai/evals/examples/simple-validation/
- Pydantic Harness background tools — explicitly not selected, as these are
  tools inside an Agent run:
  https://pydantic.dev/docs/ai/harness/background-tools/
- Python asyncio lifecycle and cancellation (not durability):
  https://docs.python.org/3.11/library/asyncio-task.html
- SQLite WAL single-writer/reader concurrency and checkpoint limitations:
  https://www.sqlite.org/wal.html
- SQLite UPSERT conflict behavior and uniqueness:
  https://www.sqlite.org/lang_upsert.html
- WHATWG SSE event ID/reconnect behavior, only for existing SSE:
  https://html.spec.whatwg.org/multipage/server-sent-events.html
- scikit-learn leakage/holdout cautions; no training library is required here:
  https://scikit-learn.org/stable/common_pitfalls.html
