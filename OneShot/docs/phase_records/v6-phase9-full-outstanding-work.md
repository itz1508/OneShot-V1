# v6.0.2 — A + B + C outstanding-work implementation (2026-10-12T04:15Z)

Append-only follow-up to :file:`v6-phase8-closure.md` and
:file:`v6-phase8-reverification.md`.

Executed under the directive **"OneShot v6.0.1 — Final Outstanding Work
Authorization"**. Scope is strictly A (Improvement Loop UI + browser E2E),
the independently executable parts of B (I05 wiring, no live inference), and
C (browser E2E race correction). No source outside the enumerated changes
was modified; the full diff is listed in `BUILD_MANIFEST.json`.

## A — Improvement Loop UI and browser E2E

**Shipped frontend wiring (reuses existing architecture, no new framework):**
- `frontend/index.html` — new `<section id="improvement-loop">` placed between
  the result summary and run-history; four collapsible details:
  job review, evaluations, improvement proposals, recurring defects.
- `frontend/app.js` — ~160 LOC appended at the end: `renderImprovementLoopForJob`,
  `renderJobReview`, `renderJobEvaluations` (approve / reject / run buttons scoped
  by evaluation status via `data-status`), `renderImprovementProposals`
  (accept / reject / mark-implemented), `renderRecurringDefects`, and a
  `DOMContentLoaded` block that wires the three forms.
- `frontend/api/client.js` — 15 new api methods matching the 15 shipped routes
  (`readJobReview`, `upsertJobReview`, `listJobReviews`,
  `createJobEvaluation`, `approveJobEvaluation`, `rejectJobEvaluation`,
  `runJobEvaluation`, `listJobEvaluations`, `readJobEvaluation`,
  `createImprovementProposal`, `listImprovementProposals`,
  `readImprovementProposal`, `acceptImprovementProposal`,
  `rejectImprovementProposal`, `markImprovementProposalImplemented`,
  `recurringDefects`).
- `frontend/styles.css` — `.improvement-loop`, `.improvement-section`,
  `.improvement-list`, `.improvement-actions`, status-colored list items.
- The panel renders only when the operator opens a committed historical job
  (reuses the existing `openHistoryJob` entrypoint). State is never written
  from the UI except through the authenticated API.

**New browser E2E** — `tests/e2e_improvement_loop.py` (14.5 KB, Chromium +
real uvicorn + SQLite + process restart). Scenarios reported on
`{"ok": true, "scenarios": [...]}` on success:
- I14-browser-run-history-navigation
- I03-browser-review-create
- I11-browser-no-apply-mutation (pre-review job == post-review job)
- I03-browser-review-update (optimistic revision increments 1 → 2)
- I06-browser-eval-propose-approve
- I08-browser-eval-run-after-approve (data-status transitions to `completed`)
- I07-browser-eval-reject-not-runnable (UI shows no Run / Approve controls)
- I10-browser-proposal-lifecycle (proposed → accepted → implemented)
- I15-browser-review-survives-restart (real `stop(proc)` + `launch` + `page2.goto`)

I01 (job trace shape) and I04 (cross-conversation isolation) remain covered
by the shipped backend tests `tests/test_improvement_loop.py`
(`test_i01_committed_job_has_trace_and_evidence`,
`test_i04_review_rejects_cross_conversation_evidence`).

### Rate-limit setting became an operator knob

The chatty UI (every improvement-loop panel renders triggers several
authenticated reads) exposed that the per-client rate limit was a hard-coded
60 req / 60 s. Promoted to `ONESHOT_RATE_LIMIT_MAX` /
`ONESHOT_RATE_LIMIT_WINDOW_SECONDS`; defaults unchanged (60 / 60). The
error message now reflects the configured values. `tests/e2e_improvement_loop.py`
sets `ONESHOT_RATE_LIMIT_MAX=2000` for its real-browser run; no other
test or production path changes behaviour.

**Verified**: `uv run --locked python -m tests.e2e_improvement_loop` returns
the OK JSON above; wired into `scripts/verify_release.py` as a new
mandatory gate `improvement_loop_browser_e2e`.

## B — I05 integration (runtime-independent)

**Current call-graph audit** (before this turn):
- `systems/model_transport.py:system_connection` / `request_text` existed.
- `systems/improvement_loop.py:run_evaluation` was deterministic-only (no
  model call) and `systems/background.py` was deterministic-only.
- No admitted operation retrieved committed job evidence and fed it to an
  advisory model. **I05 was not wired.**

**Smallest justified correction (shipped):**
- `systems/improvement_loop.py:request_advisory_analysis(store, cid, jid, settings)`
  — reads the committed artifact content + cited source ids, calls
  `model_transport.request_text` with a strict JSON contract, validates the
  response, and persists the result as an `improvement_proposals` row in
  `status='proposed'` with
  `evidence_json.model_provenance = {provider, model, kind: 'advisory_analysis'}`.
- `POST /api/conversations/{cid}/jobs/{jid}/advisory-analysis` route added to
  `systems/api.py` (authenticated + `writable_system` + CSRF).

**Explicit non-fabrication guarantee**: when
`settings.provider == 'evidence'` (the default), the call returns
HTTP 503 with
`{detail: 'MODEL_RUNTIME_UNAVAILABLE', missing_prerequisite: '...',
corrective_action: '...'}` and writes **no** row. Covered by three new
regression tests in `tests/test_i05_advisory_analysis.py`:
- `test_i05_advisory_requires_configured_provider` (503 + no proposal written)
- `test_i05_advisory_unknown_job_rejected`
- `test_i05_advisory_requires_auth`

**Live-model receiver command** (not executed from this sandbox — no local
llama-server; see `v6-phase8-reverification.md` for the sandbox footprint):

```bash
# Start a local llama-server listening on 127.0.0.1:8080 with a chat model.
# Then launch OneShot with:
export ONESHOT_PROVIDER=llama
export ONESHOT_MODEL_NAME=<your-gguf-model-id>
export ONESHOT_MODEL_ENDPOINT=http://127.0.0.1:8080/v1/chat/completions
uv run --locked python -m uvicorn systems.api:create_app --factory

# Create a job, then:
curl -X POST \
  -H "Authorization: Bearer $ONESHOT_API_TOKEN" \
  -H "X-Oneshot-CSRF: $CSRF" \
  http://127.0.0.1:8000/api/conversations/$CID/jobs/$JID/advisory-analysis
```

A successful real-model response creates one `improvement_proposals` row
whose `evidence.model_provenance` records the `provider` and `model`
actually used. The operator approves, rejects, or marks implemented via the
UI (A).

## C — Browser E2E race correction

**Reproduction attempt**: 10 isolated runs of `tests.e2e_presend` — all 10
`PRESEND_BROWSER_E2E_PASS`. The race observed in the v6.0.1 reverification
log did not reproduce. Nonetheless the smallest deterministic fix was
applied because the root cause is observable in the frontend code:

- `frontend/app.js` boot order: `boot()` reveals `#workspace` (and
  therefore `#system-input`) **before** awaiting `createConversation()`
  that writes `sessionStorage['oneshot_conversation_id']`.
- The test waited on `#system-input` visibility, then immediately read
  `sessionStorage` — a race during the `createConversation` await.

**Fix** (CSP-safe; the shipped CSP forbids `'unsafe-eval'` so
`page.wait_for_function` is NOT an option):

- `tests/e2e_browser.py` — new helper `wait_for_boot(page, timeout_ms=10000)`
  that waits for `#connection-state` to carry the exact text
  `System connected` (set by `updateConnection()` only after the awaited
  `createConversation` resolves and `state.connected=true`).
- `tests/e2e_presend.py`, `tests/e2e_prompt_workspace.py` import or
  mirror the helper and insert one call after every `#system-input` wait
  that is followed by a `sessionStorage` read.
- No sleeps, no weakened assertions, no suppressed errors.

**Validation** — 20/20 consecutive isolated runs of `tests.e2e_presend`
with the fix returned `PRESEND_BROWSER_E2E_PASS`.

## D — Acceptance-evidence reconciliation

**Verified implementation / passing API/contract tests** — 229 pytest, ruff
clean. New: `test_i05_advisory_analysis.py` (3 tests),
`test_improvement_loop.py` unchanged (8 tests).

**Passing browser E2E** — `tests/e2e_browser.py`,
`tests/e2e_presend.py`, `tests/e2e_live_model_local.py`,
`tests/e2e_backup_restore.py`, `tests/e2e_prompt_workspace.py`,
**`tests/e2e_improvement_loop.py` (new)** — all green in the latest run.

**Unexecuted external-runtime checks** — `live_model_browser_e2e`,
`vision_local_e2e`, `docker_compose_config` remain
`SKIPPED_PREREQUISITE_MISSING` with their exact missing-prerequisite
strings (unchanged from v5.4 / v6.0 / v6.0.1).

**P12 designation reconciliation (directive §D)**: the shipped scenario in
`tests/e2e_prompt_workspace.py` is `P12-precondition-missing`, exercising
the Prompt-Optimization `provider=evidence` 503 path. The P12 contract is
Prompt Optimization — real optimization with a configured model remains
`E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE`. Vision E14 is a separate
`vision_local_e2e` gate per ADR-002 and is **not** a sub-axis of P12. No
scenario was silently renamed.

## E — Final release-verification state

`uv run --locked python scripts/verify_release.py` returned **VALID** on
3 of 4 attempts; one attempt failed on an unrelated P10 compare-content
flake in `e2e_prompt_workspace.py` that is independent of this scope (the
same race the prior-turn reverification record flagged for `e2e_presend`;
future receiver follow-up).

Current gate matrix (data/verification/last_run.json): 25 mandatory OK, 3
optional skipped, 28 gates total.

## Verdict — unchanged on the model-runtime axis

- **Gate-level**: `VALID` with the new `improvement_loop_browser_e2e`
  mandatory gate.
- **Prompt Lifecycle E2E**: unchanged — 10 scenarios green; P09 and
  P12-real-model remain `E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE`;
  P11-semantic remains `REQUIRES_PRODUCT_DECISION`.
- **Improvement Loop E2E**: 9 browser scenarios green;
  **I05 is wired at the API layer and backend-tested** (3 new regression
  tests confirming the non-fabrication contract); real-model inference for
  I05 remains `E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE` until a
  llama-server (or an authorized hosted provider) is reachable.
- **Overall**: `NOT VALID — REQUIRED PROMPT LIFECYCLE AND/OR IMPROVEMENT
  LOOP E2E INCOMPLETE OR FAILED` on the `MODEL_RUNTIME_UNAVAILABLE` axis
  for P09, P12-real-model, and I05-real-model. All runtime-independent
  work is complete.
