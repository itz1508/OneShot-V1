# v6.0.5 — Verifier policy + I16 fresh-context + adversarial fixtures (2026-10-12T08:30Z)

Append-only follow-up to :file:`v6-phase11-final-reconciliation.md`.

Executed under **"OneShot v6.0.4 — Final Completion, Reconciliation and
Release Directive"**. Scope: (§2) correct the `release_ready` vs
`product_release_ready` distinction and resolve the `docker` /
`OPTIONAL_GATES` inconsistency, add regression tests enforcing the policy;
(§3) extend the I16 browser scenario with a fresh browser context + real
application restart + readback-does-not-create-state assertions; (§4)
produce the independent adversarial fixture matrix the directive lists
verbatim and the symlink / Apply security regression tests; (§6) record
the P11-semantic unresolved product-decision questions without inventing a
scoring rule.

The v6.0.4 artifacts remain the authoritative evidence of what was shipped
under that label. v6.0.5 is cut because the verifier **policy** changed
(not merely gate counts) and because new regression tests landed.

## §2 — Verifier policy change

**Changes to `scripts/verify_release.py`:**

- `OPTIONAL_GATES` now contains `docker` (in addition to the pre-existing
  `docker_compose_config`, `docker_compose_build`, `live_model_browser_e2e`,
  `vision_local_e2e`). This resolves the inconsistency the directive
  flagged: the `docker` gate was already annotated
  `Docker is an optional target; verdict is not demoted when absent`, but
  because it was not in the set its skipped state did not appear in
  `optional_skipped_gates`. The classification follows the shipped policy
  (established in v5 Phase 11), not an arbitrary move.
- New constant `REQUIRED_REALMODEL_SCENARIOS = ('P09', 'P12-real-model',
  'I05-real-model')`.
- New helper `_realmodel_scenarios_state(results)` infers each scenario's
  state from gate outcomes. A scenario is reported as `VERIFIED` only when
  its backing gate is `OK`; `SKIPPED_PREREQUISITE_MISSING` yields
  `PENDING_REALMODEL_RUNTIME`.
- `verdict()` now emits three new top-level fields:
  - `product_release_ready: bool` — strictly True iff `release_ready` is
    True **and** every scenario in `REQUIRED_REALMODEL_SCENARIOS` is
    `VERIFIED`.
  - `blocked_scenarios: list[str]` — the scenarios whose state is not
    `VERIFIED`.
  - `realmodel_scenarios: dict[str, 'VERIFIED' | 'PENDING_REALMODEL_RUNTIME']`.
- The stdout message now reads `VALID (structural) — ...` instead of the
  bare `VALID`, followed by `product_release_ready: True/False` so an
  operator can never confuse the structural verdict with the product
  release decision. The exit code behaviour is unchanged (0 iff
  `mandatory_failed == []`).

**New regression tests — `tests/test_verify_release_policy.py` (6 tests):**

- `test_docker_is_in_optional_gates`
- `test_structural_valid_with_realmodel_skipped_is_not_product_ready` —
  the key invariant the directive demands: a skipped prerequisite is not
  an executed pass; `product_release_ready` is `False` even when `status`
  is `VALID`.
- `test_structural_valid_with_realmodel_browser_ok_still_requires_i05` —
  when `live_model_browser_e2e` is `OK`, P09 and P12-real-model become
  `VERIFIED`, but I05-real-model (no shipped gate) stays
  `PENDING_REALMODEL_RUNTIME`; the product release remains gated.
- `test_mandatory_gate_failure_blocks_product_ready` — a `FAILED` ruff
  gate drives both `release_ready` and `product_release_ready` to False.
- `test_optional_skips_do_not_block_structural_valid` — the four optional
  gates (`docker`, `docker_compose_config`, `live_model_browser_e2e`,
  `vision_local_e2e`) all appear in `optional_skipped_gates` and none
  cause `NOT_VALID`.
- `test_realmodel_scenarios_require_actual_execution` — explicit:
  inferred scenario state cannot be set to `VERIFIED` without an actual
  `OK` gate.

Verdict JSON for the current sandbox:

```
status                 = VALID
release_ready          = true  (structural)
product_release_ready  = false (blocked by real-model runtime)
blocked_scenarios      = [P09, P12-real-model, I05-real-model]
realmodel_scenarios    = {P09:PENDING, P12-real-model:PENDING, I05-real-model:PENDING}
gate_count             = 29 (25 OK, 4 SKIPPED)
optional_skipped_gates = [docker, docker_compose_config,
                          live_model_browser_e2e, vision_local_e2e]
```

## §3 — I16 fresh-context + application-restart

`tests/e2e_improvement_loop_closure.py` now has **two** I16 scenarios:

1. `I16-browser-full-lifecycle` (shipped v6.0.4) — review + evaluation +
   proposal + recurring survive a browser reload inside the same
   Playwright context + same uvicorn process.
2. `I16-browser-fresh-context-and-restart` **(new)** — after the first
   scenario completes:
   - `stop(proc)` tears the real uvicorn process down.
   - A new `launch(port, data_dir)` restarts it against the same SQLite
     database.
   - A **fresh Playwright `browser` + `new_context`** is launched (no
     cookies, no sessionStorage carryover).
   - Operator re-authenticates (`#browser-password` + `#login-submit`).
   - Session storage is pinned back to the pre-restart `cid`; the page
     is reloaded.
   - Snapshot the pre-readback counts of `/job-evaluations` and
     `/improvement-proposals`.
   - Open the historical job, verify UI panels show the same review
     decision (observed_defect), a `completed` evaluation, an `accepted`
     proposal, and a non-zero recurring-defects summary.
   - Post-readback assertions: `/job-evaluations` count unchanged,
     `/improvement-proposals` count unchanged, `/jobs/{jid}` JSON byte-
     identical to the pre-readback snapshot. **No new row was created
     by the readback alone.**

Three consecutive runs returned
`{"ok": true, "scenarios": ["I09-browser-recurring-defects",
"I12-browser-baseline-candidate-compare",
"I13-browser-prompt-version-immutable", "I16-browser-full-lifecycle",
"I16-browser-fresh-context-and-restart"]}`.

## §4 — Independent adversarial fixture matrix

**New `tests/test_apply_security.py` (13 tests):**

- Parametrised `destination()` traversal / absolute / empty guard (8
  variants).
- Simple relative path accepted.
- Symlink from `applied/` pointing outside is rejected (platform-skipped
  where symlinks are not permitted).
- `/apply/prepare` requires authentication (401/403).
- `/apply/prepare` with a real artifact id and `../escape.md` rejected
  422.
- `/apply/prepare` with a real artifact id and `/etc/evil` rejected
  (400/403/404/422).

**New `tests/test_adversarial_fixtures.py` (10 tests):**

- `test_csrf_header_required_for_write_operations`.
- `test_draft_only_change_does_not_publish_a_version`.
- `test_cross_conversation_source_access_is_denied`.
- `test_duplicate_job_submission_is_idempotent` — replay the exact body
  returns `reused=True` and the same job id.
- `test_prompt_variable_values_treated_as_data` — substituted content
  is NOT re-parsed for `${…}` patterns.
- `test_job_cannot_reference_source_from_other_conversation`.
- `test_evaluation_without_approval_cannot_run`.
- `test_proposal_cannot_jump_to_implemented`.
- `test_evidence_bundle_lists_scope_sources`.
- `test_optimizer_without_configured_provider_returns_503`.

All 23 new regression tests pass. Full suite: **259 passed, 1 skipped**
(= 230 → +6 verifier policy + +13 apply security + +10 adversarial = 259).

### Test-isolation fix (not a product change)

The initial run of the new tests under the full suite caused a hang near
test ~85. Root cause: the shipped `_login` helper pattern uses
`TestClient(app).__enter__()` without ever `__exit__`-ing, which leaks
the FastAPI startup/shutdown executor between tests. With four new
modules × many sub-tests the shared `concurrent.futures` thread pool
exhausted, causing the suite to stall.

**Fix (test-only, no product change):** the four new modules thread a
`request` fixture into `_login` and register a finalizer that cleanly
`__exit__`-s the TestClient at test teardown. The pre-existing
`tests/test_improvement_loop.py` was not changed (it only runs 8 tests
and does not reproduce the leak alone). The suite now completes in
~53 s.

## §5 — Real-model boundary (unchanged)

`P09`, `P12-real-model`, `I05-real-model` remain
`E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE`. The verifier now reports
this explicitly in both human and machine-readable form:

- Stdout: `product_release_ready: False — blocked_scenarios=['P09',
  'P12-real-model', 'I05-real-model']`.
- JSON: `product_release_ready=false`, `blocked_scenarios=[...]`,
  `realmodel_scenarios={...: PENDING_REALMODEL_RUNTIME}`.

The receiver-side runbook in `v6-phase9-full-outstanding-work.md §B`
is unchanged. **No Ollama transport test, synthetic responder, or
provider-unavailable test was substituted for llama.cpp acceptance.**

## §6 — P11-semantic product-decision inventory

**New `docs/P11_SEMANTIC_DECISION.md`:**

Enumerates the four unresolved acceptance questions blocking P11-semantic:

1. Which evaluator? (LLM-as-judge / fixed goldens / operator sample)
2. What success criteria? (binary label vs scored, threshold policy)
3. What evidence envelope must be preserved?
4. Where does the evaluator plug in? (mandatory gate / UI panel / both)

**No scoring threshold or acceptance rule was invented.** The agent will
not advance P11-semantic without an operator-signed answer to these
questions.

## §7 — Final verification

| Command | Observed |
|---------|----------|
| `uv run --locked pytest` | **259 passed, 1 skipped**, 53 s |
| `uv run --locked ruff check .` | **All checks passed!** |
| `tests.e2e_improvement_loop_closure` | ok=true × 3 runs, with the new fresh-context scenario in the list |
| `scripts/verify_release.py` | **VALID (structural)** × 3 runs; `product_release_ready=False` with the exact blocked scenarios |

## §8 — Final deliverables (v6.0.5)

Per directive §8, this release includes:

- `oneshot-complete-release-2026-10-12-v6.0.5.tar.gz` — exact final source,
  frontend rebuilt by `node frontend/build.mjs` with the shipped
  `index.html` + markers.
- `oneshot-complete-release-2026-10-12-v6.0.5-SHA256SUMS.txt` — tarball
  SHA-256 + per-file SHA-256 for every file in the archive.
- `oneshot-complete-release-2026-10-12-v6.0.5.zip` — downloadable `.zip`
  containing the release AND the evidence files
  (`verify_release_last_run_v6.0.5.json` and the SHA256SUMS file).
- `verify_release_last_run_v6.0.5.json` — current verifier output.

The v6.0.4 artifacts remain unchanged as historical evidence.

## §9 — Final verdict

**`NOT VALID — MANDATORY ACCEPTANCE INCOMPLETE OR FAILED`**

Blocked / pending items (directive §9 vocabulary):

- `P09` → `E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE`
- `P12-real-model` → `E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE`
- `I05-real-model` → `E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE`
- `P11-semantic` → `REQUIRES_PRODUCT_DECISION` (see
  `docs/P11_SEMANTIC_DECISION.md`)

Promotion is **not authorized**. The verifier's structural `VALID` and
`release_ready=true` reflect only the executable, mandatory, non-model
E2E paths; `product_release_ready=false` is the authoritative product
boundary.
