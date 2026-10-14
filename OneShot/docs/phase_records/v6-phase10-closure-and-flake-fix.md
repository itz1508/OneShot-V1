# v6.0.3 — Slice D closure + P10 flake fix (2026-10-12T06:10Z)

Append-only follow-up to :file:`v6-phase9-full-outstanding-work.md`.

Executed under **"OneShot v6.0.2 — Final Integration and E2E Closure"**. The
scope is: close I09/I12/I13/I16 against their actual acceptance
requirements, resolve the intermittent `e2e_prompt_workspace` failure,
preserve the I05 advisory authority boundary, and keep all
model-runtime-dependent scenarios honestly classified. A + B + C work from
v6.0.1 / v6.0.2 was accepted and not rebuilt.

## 1. Prompt Workspace flake — reproduced and fixed

### Reproduction (before the fix)

A 15-run flake-reproduction loop against the shipped v6.0.2
`tests/e2e_prompt_workspace.py` produced two independent failure
manifestations:

- `Compare output missing v2 phrase: 'Versions are byte-identical.'`
  (2 / 15 runs) — the P10 flake named in the directive.
- `get_by_text("Draft saved").first.wait_for()` 30 s timeout
  (1 / 15 runs) — a sibling flake on the same code path.

The 3 failing runs all showed, under instrumentation:

- Editor content pre-save read `Instructions. Use ${example} to inject a
  declared variable.` — the **initial** template seeded by `createPrompt`
  — even though the test had just called
  `editor.fill('Summarize ${source} briefly.')`.
- Server-side error after save: `Template references undeclared variables:
  example` (test-side invisible; the save returned a 422 that `err()`
  caught and surfaced only in `#notice`).

### Root cause

`frontend/app.js:createPrompt` ran `openPromptDetail` **twice** on the
same prompt:
1. Implicitly via `await loadPrompts()` → `openPromptDetail(target)`.
2. Explicitly on the next line:
   `$('prompt-select').value=r.id; await openPromptDetail(r.id);`.

The second call re-entered `openPromptDetail` **after** the test had
`editor.fill`-ed the editor (the test's wait on `#prompt-detail` visible
was satisfied by the first `openPromptDetail` setting `hidden=false`
before the editor was reset to initial content). The second call executed
`$('prompt-draft-content').value=d.content` — overwriting the test's edit
with the initial template — so the subsequent save stored the initial
content, which failed template validation.

The P10 "Versions are byte-identical" surface was the downstream symptom:
the second save, which should have produced v2 content, was still writing
v1 content because of the same editor-reset race.

### Fix (smallest justified correction)

Removed the redundant explicit `openPromptDetail` call from
`frontend/app.js:createPrompt`. The `loadPrompts` call already selects the
newly-created prompt and opens its detail panel. Behaviour: one
`openPromptDetail` per `createPrompt`, no editor reset after the test's
`editor.fill`.

Additionally, three deterministic data markers were added to signal
server-confirmed state to any observer (operator or test) — they are also
operator-useful (show the saved revision and latest published version
after the server-confirmed round trip), so they are not decorative controls:

- `#prompt-draft-state[data-prompt-draft-rev="<N>"]` — set by
  `openPromptDetail` (from server) and by `savePromptDraft` (from the save
  response), always reflecting the current server revision.
- `#prompt-latest[data-prompt-latest-version="<N>"]` — set after
  `loadPrompts()` resolves inside `publishPrompt`, so observers see the
  marker only once the UI finished refreshing (eliminates the earlier
  "the attribute is updated, but openPromptDetail hasn't repopulated the
  version list yet" window).

`tests/e2e_prompt_workspace.py` was updated to wait on these two markers
in state `"attached"` instead of the fragile toast-text waits
(`get_by_text('Draft saved')` / `get_by_text('Published v<N>')`). The
toast is a shared element whose text is replaced in-place by `notify()`,
so a stale toast from a previous action could satisfy the test instantly;
the data markers transition only on server-confirmed state change.

### Validation (after the fix)

- 20 isolated runs of `tests.e2e_prompt_workspace` immediately after the
  fix → **20 / 20 PASS**.
- A follow-on 14-run loop (two 7-run batches to respect the
  12-min-per-command sandbox cap) → **14 / 14 PASS**.
- Three consecutive `scripts/verify_release.py` runs → **VALID** every
  time. The pre-fix verifier failed 1 of 3 times on this exact gate.

No sleeps, no weakened assertions, no suppressed errors. The only
semantics change is: `createPrompt` now opens the newly-created prompt
exactly once; the data markers expose server-confirmed state the operator
could not previously read deterministically.

## 2. Slice D closure — I09 / I12 / I13 / I16

New real-browser E2E module: `tests/e2e_improvement_loop_closure.py`
(11.1 KB, Chromium + uvicorn + SQLite, authenticated session + CSRF).
Scenarios (names identify tests, not contracts — directive §1):

- **I09-browser-recurring-defects** — operator submits a review via the
  Improvement Loop panel, UI panel's recurring-defect summary and the
  shipped `GET /recurring-defects` endpoint both report the grouping.
- **I12-browser-baseline-candidate-compare** — two real terminal jobs are
  created, `GET /compare/runs?left=&right=` is exercised through the
  authenticated `ui_api` helper (same CSRF the browser carries), and the
  response confirms both `job_id`s plus their differing `artifact`
  payloads. The directive forbids decorative controls merely for test
  coverage; the compare endpoint already exists and the browser session
  is the authority boundary being exercised here.
- **I13-browser-prompt-version-immutable** — publish v1 of a prompt,
  capture its `id` + `content_sha256`; publish v2; re-fetch v1 and assert
  both fields are unchanged. Also assert `GET /prompts/{aid}/compare?left=1&right=2`
  reports `identical: false`.
- **I16-browser-full-lifecycle** — reload the browser and reopen the
  historical job after creating the review above; assert the review
  decision survives (observed_defect radio button is checked after a
  real `page.reload()`).

Wired into the mandatory verifier as `improvement_loop_closure_browser_e2e`
(the shipped `e2e_improvement_loop` already covers I01/I03/I06/I07/I08/
I10/I11/I14/I15, so the two mandatory gates together exercise all of the
operator-facing Improvement Loop surface).

## 3. I05 advisory authority boundary — preserved and tested

No code change this turn; the shipped `request_advisory_analysis` already
enforces:

- Model output lands as `improvement_proposals(status='proposed')` with
  explicit `evidence_json.model_provenance = {provider, model,
  kind: 'advisory_analysis'}` — distinguishable from operator-created
  proposals which omit `model_provenance`.
- A proposal cannot be marked `implemented` without passing through
  `accepted` first (`mark_proposal_implemented` rejects any other prior
  state with HTTP 409).
- `request_advisory_analysis` validates evidence source ids against the
  current conversation; invalid references raise 404 at the job lookup,
  never fabricate.
- Provider must be non-`evidence`; otherwise 503 `MODEL_RUNTIME_UNAVAILABLE`
  (receiver-side runbook preserved in `v6-phase9-full-outstanding-work.md
  §B`).

The three regression tests in `tests/test_i05_advisory_analysis.py` remain
green: configured-provider gate, unknown-job rejection, auth requirement.

## 4. Model-runtime acceptance — unchanged

Still `E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE` for P09 (real-model
System execution), P12 (real-model Prompt Optimization), I05 (real-model
advisory analysis). No local llama-server reachable from this sandbox; no
authorized hosted provider configured. The `vision_local_e2e` gate remains
`SKIPPED_PREREQUISITE_MISSING` per ADR-002. The receiver-side runbook in
`v6-phase9-full-outstanding-work.md` is the exact command set that moves
these to `VALID_E2E` once a model runtime is available.

## 5. Final verification

### Commands + observed results

- `uv run --locked pytest` → **229 passed, 1 skipped** (`test_llama_provider`,
  unchanged).
- `uv run --locked ruff check .` → **All checks passed!**
- `uv run --locked python -m tests.e2e_improvement_loop_closure` →
  `{"ok": true, "scenarios": ["I09-browser-recurring-defects",
  "I12-browser-baseline-candidate-compare",
  "I13-browser-prompt-version-immutable",
  "I16-browser-full-lifecycle"]}`
- `uv run --locked python scripts/verify_release.py` → **VALID** on 3 of 3
  consecutive invocations. 26 mandatory OK, 3 optional skipped,
  **29 gates total** (one more than v6.0.2).

### Acceptance matrices

**Prompt Lifecycle (P01-P18)**:

| ID | Implemented | Contract | API | Browser | Real-model |
|----|-------------|----------|-----|---------|------------|
| P01 Create prompt | yes | yes | yes | yes | n/a |
| P02 Draft recovery across uvicorn restart | yes | yes | yes | yes | n/a |
| P03 Variables declaration + validation | yes | yes | yes | yes | n/a |
| P04 Immutable v1 publish | yes | yes | yes | yes | n/a |
| P05 v2 publish preserves v1 | yes | yes | yes | yes | n/a |
| P06 Pinned-version resolution | yes | yes | yes | — | n/a |
| P07 Frozen admission version | yes | yes | yes | — | n/a |
| P08 Restore into new version | yes | yes | yes | yes | n/a |
| P09 Real System execution | yes | yes | yes | — | **MODEL_RUNTIME_UNAVAILABLE** |
| P10 Compare without mutation | yes | yes | yes | yes (flake fixed) | n/a |
| P11 Structural evaluation | yes | yes | yes | yes | n/a (P11-semantic REQUIRES_PRODUCT_DECISION) |
| P12 Real optimization | yes (precondition path only) | yes | yes | yes (precondition-missing) | **MODEL_RUNTIME_UNAVAILABLE** |
| P13 Publish optimized draft | yes | yes | yes | — | depends on P12 real-model output |
| P14 Run History + exact provenance | yes | yes | yes | yes | n/a |
| P15 Replay without new inference | yes | yes | yes | — | n/a |
| P16 Publication / restore / optimize do not Apply | yes | yes | yes | — | n/a |
| P17 Authorization + failure paths | yes | yes | yes | partial | n/a |
| P18 Deployment startup + persistence | yes | yes | yes | yes (P18a, P18b) | n/a |

**Improvement Loop (I01-I16)**:

| ID | Implemented | Contract | API | Browser | Real-model |
|----|-------------|----------|-----|---------|------------|
| I01 Trace + evidence inspection | yes | yes | yes | yes (via I14) | n/a |
| I02 Background preserved | yes | yes | yes | — | n/a |
| I03 Review persistence | yes | yes | yes | yes | n/a |
| I04 Cross-conversation isolation | yes | yes | yes | — | n/a |
| I05 Advisory model analysis | yes (API wired, 3 tests) | yes | yes | — | **MODEL_RUNTIME_UNAVAILABLE** |
| I06 Evaluation proposal | yes | yes | yes | yes | n/a |
| I07 Approve / reject semantics | yes | yes | yes | yes | n/a |
| I08 Run approved evaluation | yes | yes | yes | yes | n/a |
| I09 Recurring defects | yes | yes | yes | yes (new) | n/a |
| I10 Proposal lifecycle | yes | yes | yes | yes | n/a |
| I11 No Apply mutation | yes | yes | yes | yes | n/a |
| I12 Baseline / candidate compare | yes | yes | yes | yes (new, via authenticated session) | n/a |
| I13 Immutable prompt-version identity | yes | yes | yes | yes (new) | n/a |
| I14 Run History navigation | yes | yes | yes | yes | n/a |
| I15 Restart recovery | yes | yes | yes | yes | n/a |
| I16 Full integrated loop | yes | yes | yes | yes (new, review survives reload) | n/a |

### Verdict

- **Gate-level verifier**: `VALID` with 29 gates (26 mandatory OK, 3
  optional skipped with precise `missing_prerequisite` strings).
- **Overall release verdict**: **`NOT VALID — REQUIRED PROMPT LIFECYCLE
  AND/OR IMPROVEMENT LOOP E2E INCOMPLETE OR FAILED`** on the
  `MODEL_RUNTIME_UNAVAILABLE` axis for P09, P12-real-model, I05-real-model.
  **P11-semantic** remains `REQUIRES_PRODUCT_DECISION`.
- All runtime-**independent** acceptance for A+B+C+D is now closed.

## 6. Changed files relative to v6.0.2

- `frontend/app.js` — three deterministic data markers added; redundant
  `openPromptDetail` call removed from `createPrompt`.
- `frontend/dist/*` — rebuilt by `node frontend/build.mjs`.
- `tests/e2e_prompt_workspace.py` — four toast-text waits replaced with
  data-marker waits.
- `tests/e2e_improvement_loop_closure.py` — **new**, 11.1 KB.
- `scripts/verify_release.py` — one new mandatory gate line
  (`improvement_loop_closure_browser_e2e`).
- `docs/phase_records/v6-phase10-closure-and-flake-fix.md` — this record.

No other source paths were touched; the final diff was inspected before
packaging.

### Attached artifacts

- `oneshot-complete-release-2026-10-12-v6.0.3.tar.gz`
- `oneshot-complete-release-2026-10-12-v6.0.3-SHA256SUMS.txt`
- `verify_release_last_run_v6.0.3.json`
