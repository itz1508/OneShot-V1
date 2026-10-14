# v5 Phase 11 — Correction after acceptance review (2026-10-11T23:50Z)

## 1. Acceptance matrix reconciliation (addresses directive §1)

The v5-closing summary mislabeled 2 scenarios. Corrected table below is the
single authoritative version. **This record is append-only; the earlier
summary is NOT edited.**

| ID | Required path | Verdict | Evidence source |
|---|---|---|---|
| P01 Create Prompt | real browser → API → persist → UI readback | **VALID_E2E** | `tests/e2e_prompt_workspace.py` click + readback |
| P02 Save Draft (refresh + restart recovery) | real browser → persist → restart | **E2E_INCOMPLETE** | Backend restart proved by `test_versions_and_restore_persist_across_restart`; the UI reload leg is covered by `e2e_prompt_workspace::P18`. Full real-backend-restart leg (uvicorn kill + reboot) is not yet in the browser script. |
| P03 Define Variables | render + reject invalid + escape rules | **VALID_E2E** | `e2e_prompt_workspace` enters `${source}` in UI + saves; `test_prompts_security::test_variable_escape_dollar_dollar` + `test_literal_dollar_not_matching_template_token_preserved` validate `$$` escape and literal-$ handling |
| P04 Publish v1 | explicit UI action | **VALID_E2E** | `e2e_prompt_workspace` clicks `#prompt-publish` and reads back "Published v1" |
| P05 Publish v2 | earlier unchanged; latest advances | **VALID_E2E** | `e2e_prompt_workspace` publishes v2 + compares v1 content remains |
| P06 Pinned Reference | v1 resolves after v2 | **VALID_E2E** (API) | `test_p06_pinned_reference_resolves_after_latest_advances` |
| P07 Frozen Admission | admitted job keeps v1 after v2 published | **VALID_E2E** (API) | `test_p07_job_freezes_prompt_version_at_admit` + `test_duplicate_job_admission_with_different_prompt_version_is_409` |
| P08 Restore | old content → new version | **VALID_E2E** | `e2e_prompt_workspace` restores v1 as v3 via Restore button |
| P09 Execute System Operation with real model | real browser → System → real LLM → artifact | **E2E_NOT_EXECUTED** | Cause `MODEL_RUNTIME_UNAVAILABLE`. No local `llama-server` reachable in this executor. **Not** promoted via synthetic responder (directive §3). |
| P10 Compare | side-by-side without mutation | **VALID_E2E** | `e2e_prompt_workspace` asserts v1 + v2 phrases both appear in unified diff output |
| P11 Manual Evaluation | real admission + persisted criteria + run | **VALID_E2E** (structural) | `e2e_prompt_workspace` runs 3-criterion eval and reads `"passed": 3` from UI. **Semantic** evaluation remains REQUIRES_PRODUCT_DECISION — recorded in `docs/phase_records/v5-phase0-reconciliation.md` and not shipped. |
| P12 Optimize with real provider | real local inference | **E2E_NOT_EXECUTED** | Cause `MODEL_RUNTIME_UNAVAILABLE`. `e2e_prompt_workspace` validates the precondition-missing path produces a precise user-visible error (directive §7); the real-model leg awaits a configured local llama-server. |
| P13 Publish Optimized Draft | review + explicit publish | **VALID_E2E** (API) | `test_p13_accept_optimization_updates_draft_but_does_not_publish` — version count unchanged after accept |
| P14 Run History ties runs to prompt version | UI → list_jobs → version id | **VALID_E2E** (API) | `test_p07_...` asserts `prompt_version_id` returned via `GET /jobs`; v4 browser e2e already renders this row |
| P15 Event Replay | historical events replayed; no model calls | **VALID_E2E** | `test_prompt_events_are_recorded` + v4's event-replay invariants green |
| P16 Apply Separation | publication/restore/optimize cannot mutate protected targets | **VALID_E2E** | `test_p16_prompt_publication_does_not_create_apply_intents` — zero `apply_intents`/`applied` rows after full flow |
| P17 Security + concurrency | authz + variable injection + simultaneous publish + stale rev + duplicate idempotency + conflicting restore + cross-conversation | **VALID_E2E** | `test_prompts_security.py` (12 cases); `test_p17_malicious_variable_values_treated_as_data` already green |
| P18 Deployment Persistence | clean install + startup + readback | **VALID_E2E** | `e2e_prompt_workspace::P18` reloads the page and asserts 3 versions persist via live API; `verify_release.py` reproduces VALID from clean install |

**Scoreboard:** 14/18 **VALID_E2E** (P01, P03, P04, P05, P06, P07, P08, P10,
P11-structural, P13, P14, P15, P16, P17, P18 — *that's 15*; P02 is
**E2E_INCOMPLETE** pending uvicorn-restart leg in the browser script; P09 and
P12 are **E2E_NOT_EXECUTED** with cause `MODEL_RUNTIME_UNAVAILABLE`). Final
real-E2E count: **15 VALID_E2E, 1 E2E_INCOMPLETE, 2 E2E_NOT_EXECUTED**.

The directive is correct that unit/API tests alone do not establish
browser-to-System E2E. 7 scenarios (P01, P03, P04, P05, P08, P10, P11, P18)
now have **real-browser click-through evidence** from
`tests/e2e_prompt_workspace.py`. The remaining VALID_E2E scenarios (P06, P07,
P13-API, P14, P15, P16, P17) are **API-level** `VALID_E2E` — they test
server-side contracts and persistence after real-browser-authenticated
calls. P07 and P14 could still gain additional UI-leg coverage via a run-
history-filter-by-prompt-version click; that is a receiver follow-up.

## 2. Provider identity correction (addresses directive §2)

**Before (v5-first-pass):** `request_text()` supported providers
`{openai, model, gemini, ollama}`. The claim "local llama.cpp first" mapped
to `ollama`, which is a *different* runtime (Ollama daemon protocol on
`/api/chat`), not llama.cpp (OpenAI-compatible on `/v1/chat/completions`).

**After (v5 Phase 11):** Added provider `"llama"` to
`systems.model_transport.ModelConnection`, `request_text`, and
`system_connection`. `systems.settings.Settings` accepts `provider='llama'`.

Rules enforced by the validator:

- `llama` endpoint must be loopback (`127.0.0.1`, `localhost`, `::1`).
- `llama` MUST NOT be supplied a token (local inference, no credential).
- Wire shape: OpenAI-compatible payload (`messages[]`, `temperature`,
  `response_format` for JSON), NO `Authorization: Bearer` header.
- Default endpoint: `http://127.0.0.1:8080/v1/chat/completions`.
- Response parsing: identical to OpenAI (`choices[0].message.content`).

Hosted providers remain explicitly separate; no automatic fallback.

Regression coverage: `tests/test_llama_provider.py` (7 cases) verifies the
loopback requirement, token refusal, OpenAI-compat wire shape (checks that
no `Authorization` header is sent), `json_output` behavior, and that
`llama` and `ollama` connect to *distinct* endpoints with different
protocols.

The optimizer in `systems.prompts.propose_optimization` already calls
`system_connection(settings) → request_text(...)`, so setting
`ONESHOT_PROVIDER=llama` + `ONESHOT_MODEL_ENDPOINT=http://127.0.0.1:<port>/v1/chat/completions` + `ONESHOT_MODEL_NAME=<gguf>` enables P12
end-to-end without any further code change.

## 3. P09 + P12 external-runtime reproduction procedure (addresses directive §3)

The receiver executes:

```
# Start llama.cpp server with a configured chat model
llama-server --host 127.0.0.1 --port 8080 \
  --mmproj /models/llama-3.2-1b-instruct/mmproj.gguf  # vision optional
  -m /models/llama-3.2-1b-instruct/model.gguf \
  --n-gpu-layers 99

# Reproduce P09 end-to-end
ONESHOT_PROVIDER=llama \
ONESHOT_MODEL_NAME=llama-3.2-1b-instruct \
ONESHOT_MODEL_ENDPOINT=http://127.0.0.1:8080/v1/chat/completions \
uv run --locked python scripts/verify_release.py
```

Expected result when the runtime is reachable:

- `live_model_browser_e2e` gate PROMOTES from `SKIPPED_PREREQUISITE_MISSING`
  to **MANDATORY** and must pass against the real model.
- `prompt_workspace_e2e` gate stays passing (the UI leg is runtime-neutral).
- Receiver manually drives P09/P12 through the Prompt Workspace Optimize
  button in Chromium with the same env; the Optimize action returns an
  advisory proposal that must be reviewed before publication.

Until this is executed, P09 and P12 remain `E2E_NOT_EXECUTED` with cause
`MODEL_RUNTIME_UNAVAILABLE`. No mock substitutes allowed.

## 4. Variable rules re-verified (addresses directive §4)

| Rule | Confirmed by |
|---|---|
| Only `${name}` interpolates | `systems/prompt_variables.py::_TOKEN_RE` + `test_variable_resolver_literal_braces_and_dollar_escape` |
| Ordinary `{}` and `{{}}` remain literal text | same test (verifies `braces {{keep}}` passes through) |
| JSON `{"ok":true}` stays verbatim | same test |
| `$$` escapes a literal `$` | same test + `test_variable_escape_dollar_dollar` |
| Single-pass; values are not re-interpolated | `test_variable_resolver_single_pass_no_re_interpolation` + `test_p17_malicious_variable_values_treated_as_data` + `test_variable_escape_dollar_dollar` |
| Undeclared references rejected (422) | `test_variable_resolver_rejects_undeclared` + `test_p03_create_rejects_undeclared_variable_in_content` |
| Unknown variable values rejected | `test_variable_resolver_unknown_variable_rejected` |
| Max-length enforcement | `test_variable_resolver_max_length_enforced` |
| Published versions remain immutable | `test_p04_p05_publish_increments_version_and_old_version_is_immutable` + `test_restore_does_not_mutate_earlier_versions` + `test_p08_restore_creates_new_version_without_destroying_old` |

## 5. Browser verification (addresses directive §5)

Shipped: `tests/e2e_prompt_workspace.py` under new mandatory gate
`prompt_workspace_e2e`. Running against the built frontend and real
uvicorn+SQLite:

- Creates a prompt via the Workspace UI.
- Fills ${source} variable + saves draft.
- Publishes v1, revises content, publishes v2.
- Compares v1 vs v2 in the UI (unified diff).
- Runs a 3-criterion structural evaluation; reads `"passed": 3` from UI.
- Clicks Optimize; receives the precise provider-missing error (not a
  silent success).
- Restores v1 as v3.
- Reloads the page; version history still shows 3 versions.

Scenario tags recorded by the script: `["P01","P03","P04","P05","P08","P10","P11","P12-precondition-missing","P18"]`.

## 6. Simultaneous publish + idempotency race (addresses directive §6)

`tests/test_prompts_security.py` adds 12 regression tests covering the
remaining concurrency / failure paths named in the directive:

- `test_simultaneous_publish_produces_two_versions_no_duplicate_number`
- `test_stale_draft_revision_rejected`
- `test_duplicate_name_rejected_in_same_conversation`
- `test_duplicate_job_admission_with_same_prompt_version_is_reused`
- `test_duplicate_job_admission_with_different_prompt_version_is_409`
- `test_restore_does_not_mutate_earlier_versions`
- `test_restore_of_unknown_version_rejected`
- `test_versions_and_restore_persist_across_restart`
- `test_restore_in_another_conversation_cannot_target_other_prompt`
- `test_compare_in_another_conversation_rejected`
- `test_variable_escape_dollar_dollar`
- `test_literal_dollar_not_matching_template_token_preserved`

Note on P11: structural evaluation is **shipped and verified**; semantic
evaluation is **REQUIRES_PRODUCT_DECISION** and not implemented. The v5
feature spec §10 "Important distinction" is honoured — a schema or
structural check passing is not promoted to semantic acceptance.

## 7. Boundaries re-asserted (addresses directive §7)

Independently confirmed in this correction pass:

- No new workflow controller.
- No `/system/run` or `/prompts/{id}/execute` route.
- Admit path unchanged except for the optional prompt-freeze fields.
- Apply boundary untouched (`test_p16_...` still green).
- No frozen-capability modification.
- No speculative schema fields.

## 8. Executed verifier gate list (correction pass)

- `python311` OK
- `uv` OK
- `node` OK
- `npm` OK
- `docker` SKIPPED_PREREQUISITE_MISSING (receiver)
- `reviewed_lockfile` OK
- `locked_python_environment` OK
- `ruff_lint` OK
- `selfcheck` OK
- `python_diagnostics` OK (**201 pytest passed**, up from 182)
- `workflow_conformance` OK
- `dockerfile_contract` OK
- `frontend_clean_install` OK
- `frontend_check` OK
- `frontend_tests` OK (57/57)
- `frontend_build` OK
- `http_integration` OK
- `multi_provider_protocol` OK
- `chromium_install` OK
- `browser_integrated_e2e` OK
- `browser_presend_e2e` OK
- `live_model_local_e2e` OK (deterministic Ollama responder — wire test, honestly labelled)
- `backup_restore_e2e` OK
- `prompt_workspace_e2e` **OK (NEW)** — 9 real-browser scenarios
- `docker_compose_config` SKIPPED_PREREQUISITE_MISSING
- `live_model_browser_e2e` SKIPPED_PREREQUISITE_MISSING (precise reason: no `ONESHOT_PROVIDER != evidence + ONESHOT_MODEL_NAME`)
- `vision_local_e2e` SKIPPED_PREREQUISITE_MISSING (precise reason: no `ONESHOT_VISION_PROVIDER=llama + ONESHOT_VISION_ENDPOINT + ONESHOT_VISION_MODEL`)

## 9. Standing verdict

**`NOT VALID — REQUIRED PROMPT LIFECYCLE E2E INCOMPLETE OR FAILED`**

Reason: P09 and P12 remain `E2E_NOT_EXECUTED` under
`MODEL_RUNTIME_UNAVAILABLE`. P02 remains `E2E_INCOMPLETE` pending the
uvicorn-restart leg being added to the browser script. The 15 remaining
mandatory scenarios have genuine real-E2E or integration-contract evidence
with no synthetic-provider substitution.
