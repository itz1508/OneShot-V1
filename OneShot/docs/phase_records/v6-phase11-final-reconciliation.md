# v6.0.4 — Reconciliation + I16 strengthening + P15 regression test (2026-10-12T06:50Z)

Append-only follow-up to :file:`v6-phase10-closure-and-flake-fix.md`.

Executed under **"OneShot v6.0.3 — Final Acceptance Reconciliation"**. Scope:
reconcile the shipped v6.0.3 gate-counting narrative, strengthen the
I16-browser scenario so it no longer rests on a single review's persistence,
and add a deterministic P15 regression test. The v6.0.3 verdict JSON itself
required **no correction** — the file was accurate.

## 1. Gate-count reconciliation (no evidence rewrite)

The shipped `verify_release_last_run_v6.0.3.json` records exactly:

- `gate_count = 29`
- 25 gates with `status = "OK"`
- 4 gates with `status = "SKIPPED_PREREQUISITE_MISSING"`
  (`docker`, `docker_compose_config`, `live_model_browser_e2e`,
  `vision_local_e2e`)
- `optional_skipped_gates = ["docker_compose_config",
  "live_model_browser_e2e", "vision_local_e2e"]` — the `docker` gate is
  itself not in `OPTIONAL_GATES` (that set lists `docker_compose_config` and
  `docker_compose_build`), which is why it does not appear in the summary
  array even though its status is skipped.
- `release_ready = true` because `mandatory_failed = []` (all non-optional
  gates have `status in {"OK", "SKIPPED_PREREQUISITE_MISSING"}`).

The v6.0.3 chat summary stated "26 mandatory OK / 3 optional skipped" — this
was a misreading of the summary payload. The authoritative figures are
**25 OK / 4 SKIPPED, 29 total**. The shipped evidence JSON is correct;
only the chat narrative needs this correction, and no release artifact is
re-cut solely for a numeric correction (directive §6).

## 2. I16-browser strengthening — reviewed + evaluation + proposal + recurring

The v6.0.3 `I16-browser-full-lifecycle` scenario in
`tests/e2e_improvement_loop_closure.py` only verified that the review
decision survived a browser reload. Per directive §2, that is not enough to
classify the Improvement Loop lifecycle complete when additional mandatory
transitions remain untested.

Strengthened the scenario to:

1. Seed a completed evaluation (criteria `{kind: contains, value: baseline}`
   proposed → approved → run → completed).
2. Seed an accepted improvement proposal (proposed → accepted) referencing
   the baseline job id.
3. Reload the browser twice (page-level, then session-storage-rebind) and
   reopen the same historical job.
4. Assert — via a mix of UI panel readback and authenticated `ui_api`
   recall through the browser session — that **all four** classes of
   findings persisted:
   - Review decision (`observed_defect` radio checked).
   - Evaluation `data-status="completed"` row attached in the panel.
   - Proposal `data-status="accepted"` row attached in the panel.
   - Recurring-defects summary still non-zero (both DOM text and API JSON).

Three consecutive runs of
`uv run --locked python -m tests.e2e_improvement_loop_closure` returned
`{"ok": true, "scenarios": ["I09-browser-recurring-defects",
"I12-browser-baseline-candidate-compare",
"I13-browser-prompt-version-immutable", "I16-browser-full-lifecycle"]}`.

No new UI controls were added — the scenario exercises the exact panel
behaviour shipped in v6.0.2 (directive §2 explicitly forbids inventing
controls to inflate browser coverage).

## 3. P15 regression test — replay without new inference

`tests/test_p15_replay_no_new_inference.py` (new, 3.3 KB) exercises the
accepted P15 contract: reading a historical terminal job's artifact must
not trigger a new model call, mutate the job row, or produce new events.
It runs a real `inspect_sources` job (deterministic under
`ONESHOT_PROVIDER='evidence'`), reads the artifact + evidence endpoints
five times, and asserts:

- `GET /jobs/{jid}` returns the exact same JSON before and after.
- The max event sequence in `/events?after=0&limit=500` is unchanged.

This is a runtime-independent regression; the real-model variant of P15
(replay a job whose artifact was produced by a configured provider) is
subsumed by the P09 real-model receiver-side runbook already shipped.

## 4. Real-model boundary — unchanged

Still `E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE` for P09, P12, I05.
No local llama-server reachable; no authorized hosted provider. Per
directive §4, Ollama transport tests, synthetic responders, and
provider-missing tests are **not** substitutes for llama.cpp acceptance.
The receiver-side runbook in `v6-phase9-full-outstanding-work.md §B`
remains the exact command set that moves these to `VALID_E2E` once a
llama-server is available.

## 5. Semantic evaluation — unchanged

**P11-semantic** remains `REQUIRES_PRODUCT_DECISION`. No semantic
scoring, no new requirements introduced.

## 6. Final verification (after this turn's changes)

- `uv run --locked pytest` → **230 passed, 1 skipped**
  (`test_llama_provider`, unchanged).
- `uv run --locked ruff check .` → **All checks passed!**
- `uv run --locked python -m tests.e2e_improvement_loop_closure` →
  **ok=true** on three consecutive runs.
- `uv run --locked python scripts/verify_release.py` → **VALID** on three
  consecutive runs. 29 gates total; 25 OK, 4 SKIPPED_PREREQUISITE_MISSING
  (`docker`, `docker_compose_config`, `live_model_browser_e2e`,
  `vision_local_e2e`); `mandatory_failed_gates = []`.

## 7. Corrected acceptance matrices

**Prompt Lifecycle (P01-P18)** — distinguishing contract/API tests from
real-browser E2E and real-model acceptance:

| ID | Implemented | Contract/API | Browser E2E | Real-model E2E |
|----|-------------|--------------|-------------|----------------|
| P01 Create prompt | yes | yes | yes (prompt_workspace) | n/a |
| P02 Draft recovery across uvicorn restart | yes | yes | yes (prompt_workspace, P02-uvicorn-restart) | n/a |
| P03 Variables declaration + validation | yes | yes | yes | n/a |
| P04 Immutable v1 publish | yes | yes | yes | n/a |
| P05 v2 publish preserves v1 | yes | yes | yes | n/a |
| P06 Pinned-version resolution | yes | yes (`test_p06_pinned_reference_resolves_after_latest_advances`) | — (API-level verified) | n/a |
| P07 Frozen admission version | yes | yes (`test_p07_job_freezes_prompt_version_at_admit`) | — (API-level verified) | n/a |
| P08 Restore into new version | yes | yes | yes | n/a |
| P09 Real System execution | yes (pipeline) | yes (evidence provider) | — | **MODEL_RUNTIME_UNAVAILABLE** |
| P10 Compare without mutation | yes | yes | yes (flake fixed in v6.0.3) | n/a |
| P11-structural | yes | yes | yes | n/a |
| P11-semantic | — | — | — | **REQUIRES_PRODUCT_DECISION** |
| P12 Real optimization | yes (precondition path) | yes | yes (precondition-missing) | **MODEL_RUNTIME_UNAVAILABLE** |
| P13 Publish optimized draft | yes | yes (`test_p13_accept_optimization_updates_draft_but_does_not_publish`) | — (depends on P12 real-model output) | **blocked by P12** |
| P14 Run History + exact provenance | yes | yes | yes (prompt_workspace) | n/a |
| P15 Replay without new inference | yes | yes (`test_p15_artifact_readback_does_not_advance_state`, **new**) | — (contract pure DB read) | n/a |
| P16 Publication / restore / optimize do not Apply | yes | yes (`test_p16_prompt_publication_does_not_create_apply_intents`) | — (API-level verified) | n/a |
| P17 Authorization + failure paths | yes | yes (`test_p17_unauth_prompt_requests_rejected`, `test_p17_cross_conversation_prompts_isolated`, `test_p17_malicious_variable_values_treated_as_data`) | — (API-level verified) | n/a |
| P18 Deployment startup + persistence | yes | yes | yes (P18a, P18b in prompt_workspace) | n/a |

**Improvement Loop (I01-I16)**:

| ID | Implemented | Contract/API | Browser E2E | Real-model E2E |
|----|-------------|--------------|-------------|----------------|
| I01 Trace + evidence inspection | yes | yes (`test_i01_committed_job_has_trace_and_evidence`) | yes (via I14 in improvement_loop_browser) | n/a |
| I02 Background preserved | yes (shipped v5) | yes (`test_background.py`) | — (not operator-facing) | n/a |
| I03 Review persistence | yes | yes (`test_i03_review_persists_and_cannot_mutate_original_job`) | yes (improvement_loop_browser) | n/a |
| I04 Cross-conversation isolation | yes | yes (`test_i04_review_rejects_cross_conversation_evidence`) | — (API-level verified) | n/a |
| I05 Advisory model analysis | yes (API wired v6.0.2) | yes (3 regression tests) | — (no UI control; prerequisite for real-model) | **MODEL_RUNTIME_UNAVAILABLE** |
| I06 Evaluation proposal | yes | yes (`test_i06_evaluation_requires_approval_before_run`) | yes (improvement_loop_browser) | n/a |
| I07 Approve / reject semantics | yes | yes (`test_i07_rejected_criteria_do_not_become_runnable`) | yes (improvement_loop_browser) | n/a |
| I08 Run approved evaluation | yes | yes (`test_i07_rejected_criteria_do_not_become_runnable` covers the inverse) | yes (improvement_loop_browser, I08-browser-eval-run-after-approve) | n/a |
| I09 Recurring defects | yes | yes (DB aggregation) | yes (improvement_loop_closure, I09-browser-recurring-defects) | n/a |
| I10 Proposal lifecycle | yes | yes (`test_i10_proposal_round_trip_and_scope_isolation`) | yes (improvement_loop_browser) | n/a |
| I11 No Apply mutation | yes | yes (`test_i11_improvement_flow_does_not_touch_apply_tables`) | yes (improvement_loop_browser) | n/a |
| I12 Baseline / candidate compare | yes | yes (`/compare/runs` endpoint) | yes (improvement_loop_closure, I12-browser-baseline-candidate-compare) | n/a |
| I13 Immutable prompt-version identity | yes | yes (prompt version SHA preserved) | yes (improvement_loop_closure, I13-browser-prompt-version-immutable) | n/a |
| I14 Run History navigation | yes | yes | yes (improvement_loop_browser, I14-browser-run-history-navigation) | n/a |
| I15 Restart recovery | yes | yes | yes (improvement_loop_browser, I15-browser-review-survives-restart) | n/a |
| I16 Full integrated loop | yes | yes | yes (improvement_loop_closure, **strengthened**: review + evaluation + proposal + recurring survive reload) | n/a |

## 8. Changed files relative to v6.0.3

- `tests/e2e_improvement_loop_closure.py` — I16 scenario strengthened; one
  f-string prefix removed to clear ruff.
- `tests/test_p15_replay_no_new_inference.py` — **new**, 3.3 KB.
- `docs/phase_records/v6-phase11-final-reconciliation.md` — this record.

No frontend code change this turn. The shipped v6.0.3 UI already exposes
every panel the strengthened I16 scenario exercises.

## 9. Release-artifact decision

Per directive §6 ("Do not issue another release solely for documentation
or renumbering unless the existing release evidence requires correction"):

- The v6.0.3 shipped artifacts remain the authoritative release.
- This turn produces a **v6.0.4 artifact** anyway because the test suite
  itself changed — the I16-browser scenario was strengthened and a new
  P15 regression was added. Shipping a new tarball keeps the "what
  passes" and "what the tarball contains" synchronized.
- The v6.0.3 verdict JSON file was NOT altered; its gate counts were
  only mis-narrated in chat.

### Attached artifacts

- `oneshot-complete-release-2026-10-12-v6.0.4.tar.gz`
- `oneshot-complete-release-2026-10-12-v6.0.4-SHA256SUMS.txt`
- `verify_release_last_run_v6.0.4.json`

## 10. Final verdict

- **Gate-level verifier**: `VALID` with 29 gates (25 OK, 4 SKIPPED).
- **Overall release verdict**: **`NOT VALID — REQUIRED PROMPT LIFECYCLE
  AND/OR IMPROVEMENT LOOP E2E INCOMPLETE OR FAILED`** on the
  `MODEL_RUNTIME_UNAVAILABLE` axis for P09, P12-real-model,
  I05-real-model. **P11-semantic** remains `REQUIRES_PRODUCT_DECISION`.
- All runtime-independent acceptance for A + B + C + D is now closed,
  and the I16 lifecycle scenario covers all three findings classes
  (review, evaluation, proposal) across a real reload.
