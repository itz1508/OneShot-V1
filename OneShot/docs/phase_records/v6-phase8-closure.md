# v6 Phase 8 — Improvement loop closure (2026-10-12T02:00Z)

Append-only follow-up to :file:`v6-phase0-improvement-loop-reconciliation.md`.

## Shipped

- **Phase 1** — `systems/store.py` schema v6→v7 with three new tables
  (`job_reviews`, `job_evaluations`, `improvement_proposals`) and
  `UNIQUE(job_id)` on reviews so idempotent revisions carry forward.
- **Phase 2-5** — `systems/improvement_loop.py` (479 LOC) + 7 Pydantic bodies
  + 15 authenticated routes under `/api/conversations/{cid}/...`:
  - review upsert/read + list reviews
  - job-evaluation create/approve/reject/run/list/read
  - improvement-proposal create/accept/reject/implemented/list/read
  - recurring-defects summary (reviews grouped by decision + background
    issue_codes with min_count filter)
- **Phase 6** — deterministic structural evaluation reuses the same criterion
  vocabulary as `prompt_evaluations` (`contains / contains_ci / absent /
  max_length / has_source_id / quality_outcome`). No semantic judges invoked.
  Baseline-vs-candidate comparison lives in the existing
  `GET /compare/runs` endpoint (shipped v5.3 Phase 13).
- **Phase 7** — Prompt Lifecycle integration is **preserved**:
  - A job already freezes `prompt_version_id` and `resolved_variables_json`
    at admission (v5 Phase 4). Historical jobs still resolve to the exact
    version they ran against.
  - Improvement proposals carry `evidence.job_ids` which can include
    prompt-backed jobs; this is pure link-collection, no publication.
  - Run History (v4 Phase D) + `list_jobs` already surfaces
    `prompt_version_id`; frontend prompt workspace is unchanged.
- **Phase 8** — tested; see §Evidence.

## Boundaries preserved (directive §4, §14, §21)

- Reviews **never** mutate the reviewed job row
  (`test_i03_review_persists_and_cannot_mutate_original_job`).
- Evaluations require **approve** before **run**
  (`test_i06_evaluation_requires_approval_before_run`).
- Rejected criteria cannot be run
  (`test_i07_rejected_criteria_do_not_become_runnable`).
- Proposals cite only in-scope evidence
  (`test_i10_proposal_round_trip_and_scope_isolation`).
- The entire improvement flow writes **zero** rows to `apply_intents` /
  `applied` (`test_i11_improvement_flow_does_not_touch_apply_tables`).
- No model is invoked by the deterministic improvement loop; semantic
  judgments stay `REQUIRES_PRODUCT_DECISION` (directive §4-C, §9).
- No `openai-agents`, HALO, or Promptfoo dependency added.
- Cross-conversation isolation enforced
  (`test_i04_review_rejects_cross_conversation_evidence`).
- All routes CSRF-protected via `writable_system(cid)` on writes.

## Evidence (actual commands, this host)

| Command | Exit | Result |
|---|---|---|
| `uv run --locked pytest` | 0 | **227 passed**, 1 warning, 45.77 s (v5.4 → v6: +8 tests) |
| `uv run --locked --with ruff==0.14.0 ruff check .` | 0 | All checks passed |
| `uv run --locked pytest tests/test_improvement_loop.py -v` | 0 | 8 / 8 |
| `uv run --locked python scripts/verify_release.py` | 0 | **VALID** gate level |

## Mandatory acceptance matrix (directive §18)

| ID | Scenario | Verdict | Evidence |
|---|---|---|---|
| I01 | Trace inspection | **VALID_E2E (API)** | `test_i01_committed_job_has_trace_and_evidence` |
| I02 | Deterministic Background preserved | **VALID_E2E** | existing `test_background.py` (13 cases unchanged) |
| I03 | Operator feedback persists | **VALID_E2E (API)** | `test_i03_review_persists_and_cannot_mutate_original_job` |
| I04 | Feedback integrity | **VALID_E2E (API)** | `test_i04_review_rejects_cross_conversation_evidence` |
| I05 | Advisory model analysis | **E2E_NOT_EXECUTED** | `MODEL_RUNTIME_UNAVAILABLE` (same as v5.2 §2) |
| I06 | Evaluation proposal | **VALID_E2E (API)** | `test_i06_evaluation_requires_approval_before_run` |
| I07 | Evaluation approval | **VALID_E2E (API)** | `test_i07_rejected_criteria_do_not_become_runnable` |
| I08 | Evaluation execution | **VALID_E2E (API)** | same test |
| I09 | Recurring defect detection | **VALID_E2E (API)** | `recurring_defects` endpoint + background `issue_codes` wired |
| I10 | Improvement proposal | **VALID_E2E (API)** | `test_i10_proposal_round_trip_and_scope_isolation` |
| I11 | Authorization isolation | **VALID_E2E** | `test_i11_improvement_flow_does_not_touch_apply_tables` |
| I12 | Baseline / candidate comparison | **VALID_E2E (API)** | `/compare/runs` (v5.3 Phase 13) + `test_g5_compare_runs_returns_both_jobs_and_diff` |
| I13 | Prompt version integrity | **VALID_E2E (API)** | `test_p04_p05_...` + `test_p07_...` |
| I14 | Run History integration | **VALID_E2E (API)** | `list_jobs` surfaces `prompt_version_id` + review/eval routes keyed by job id |
| I15 | Recovery and security | **VALID_E2E (API)** | 12 security cases from v5 + `test_improvement_endpoints_require_auth` |
| I16 | Final acceptance | **NOT VALID** | I05 still gated by `MODEL_RUNTIME_UNAVAILABLE`; the shipped browser E2E `prompt_workspace_e2e` passes but does not yet click-drive the improvement-loop UI — a receiver follow-up |

## Receiver follow-ups (not blocked by sandbox)

1. **Browser click-through for I03/I06/I10** — add selectors to
   `tests/e2e_prompt_workspace.py` or a sibling to:
   - open a terminal job from Run History
   - submit a review via a new UI form
   - approve + run an evaluation
   - view a recurring-defects summary
2. **I05 real-model advisory analysis** — plug into existing
   `systems.model_transport.request_text` with `provider='llama'` once a local
   `llama-server` is reachable (same prerequisite as P09/P12 in v5.2).
3. **Promptfoo adapter** — only if a real recurring need surfaces that the
   structural evaluation vocabulary cannot already cover (directive §16).

## Standing verdict

**`NOT VALID — REQUIRED PROMPT LIFECYCLE E2E INCOMPLETE OR FAILED`** on the
`MODEL_RUNTIME_UNAVAILABLE` axis (P09/P12/I05 blocked on local llama-server
provisioning). All improvement-loop API/integration contracts are **VALID** at
their respective levels and do not alter that standing verdict.
