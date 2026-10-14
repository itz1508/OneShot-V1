# OneShot — End-to-End Verification Matrix (v6.0.7+)

**Policy:** Every mandatory E2E path has a dedicated executable suite in `tests/`.
Each row below names the suite, the actual command used, and the outcome
captured on 2026-10-12.

Not equated:
- Structural verifier `VALID` ≠ full System E2E verified.
- Suite PASS against local protocol stubs ≠ real-model acceptance.
- `product_release_ready` requires BOTH real-model execution AND P11-semantic sign-off.

Execute everything from the project root:

```sh
UV_PROJECT_ENVIRONMENT=/tmp/uv-env uv sync --locked --extra test --python 3.11
cd frontend && node build.mjs && cd ..
uv run --locked python -m playwright install --with-deps chromium
```

## Pytest unit + integration

| Command | Collected | Pass | Skip | Fail |
|---|---:|---:|---:|---:|
| `uv run --locked python -m pytest` | 307 | **305** | 2 | 0 |

Covers: workflow, store, atomic migrations, source atomicity, backup/applied,
apply security, worker stall + lifecycle, verifier policy / evidence,
contracts, prompts, improvement loop, I05 advisory, vision scanner, release
packaging, release verdict policy, and more. See `tests/` for the full list.

## System E2E (real uvicorn + real worker + real HTTP)

| ID | Suite | Executed command | Outcome | Notes |
|---|---|---|---|---|
| E01 | `tests.e2e_http` | `uv run python -m tests.e2e_http` | **PASS** | real uvicorn, cookie+csrf auth, SSE, Apply readback, restart durability |
| E03b | `tests.e2e_multi_provider_http` | `uv run python -m tests.e2e_multi_provider_http` | **PASS** | multi-provider HTTP against local protocol stub (openai/gemini/ollama); `external_model_semantics_verified=false` |
| E10 | `tests.e2e_backup_restore` | `uv run python -m tests.e2e_backup_restore` | **PASS** | real uvicorn, backup → verify → restore → readback with byte-equal `applied_sha256 == restored_sha256` |

## Browser E2E (real Chromium against real uvicorn)

| ID | Suite | Scenarios | Outcome |
|---|---|---|---|
| E05 | `tests.e2e_browser` | authentication, source bind, admission, SSE, Apply, restart persistence, uninstalled-agent block | **PASS** |
| E05b | `tests.e2e_presend` | approved_exact=1, original_preserved=1, direct_send=1, cancel=0 | **PASS** |
| E06 | `tests.e2e_prompt_workspace` | P01, P02-uvicorn-restart, P03, P04, P05, P08, P10, P11, P12-precondition-missing, P18 | **PASS** |
| E07 | `tests.e2e_improvement_loop` | I03-review-create/update, I06-eval-propose-approve, I07-eval-reject, I08-eval-run-after-approve, I10-proposal-lifecycle, I11-no-apply-mutation, I14-run-history-navigation, I15-review-survives-restart | **PASS** |
| E07b | `tests.e2e_improvement_loop_closure` | I09-recurring-defects, I12-baseline-candidate-compare, I13-prompt-version-immutable, I16-full-lifecycle, I16-fresh-context-and-restart | **PASS** |

## Live-model E2E (protocol stub)

| ID | Suite | Outcome | Notes |
|---|---|---|---|
| E09 | `tests.e2e_live_model_local` | **PASS** | local Ollama-protocol stub on 127.0.0.1 (loopback-only); verifies worker admission → provider call → artifact kind=model_generated → events persisted |

## Real-model acceptance (BLOCKED on external prerequisites)

| ID | Suite | Required prerequisite | Outcome |
|---|---|---|---|
| P09 | `tests.e2e_live_model` + signed `realmodel_evidence/P09.json` | `ONESHOT_PROVIDER ∈ {openai, gemini, ollama, model}` + `ONESHOT_MODEL_NAME` + `ONESHOT_EVIDENCE_HMAC_KEY` | **PENDING_REALMODEL_RUNTIME** |
| P12-real-model | prompt optimizer with non-evidence provider + signed `P12-real-model.json` | same + a published prompt | **PENDING_REALMODEL_RUNTIME** |
| I05-real-model | advisory analysis with non-evidence provider + signed `I05-real-model.json` | same + a committed job | **PENDING_REALMODEL_RUNTIME** |
| vision-local | `tests.e2e_vision_local` | `ONESHOT_VISION_PROVIDER=llama` + `ONESHOT_VISION_ENDPOINT` + `ONESHOT_VISION_MODEL` + vision-capable GGUF | **PREREQUISITE_MISSING** |

Per directive §6, these are **NOT** reported as completed when the authorized
llama.cpp runtime is unavailable. The verifier output explicitly refuses to
mark them VERIFIED without:

1. A signed evidence file at `data/realmodel_evidence/<scenario>.json`.
2. A matching artifact row in `data/oneshot.sqlite3` with correct scenario→operation mapping.
3. A current release identity (`.git` HEAD or `BUILD_MANIFEST.host.git_sha`).
4. A fresh (non-replayed) nonce.

## Semantic acceptance (P11-semantic)

| ID | Requirement | Status |
|---|---|---|
| P11-semantic | Resolution sentinel at `docs/product_decisions/P11-semantic.resolved.json` with `decision`, `approved_by`, `approved_at` | **UNRESOLVED** |

The agent does NOT author this sentinel — see `docs/P11_SEMANTIC_DECISION.md`
for the four open product questions. Per directive §7, unresolved mandatory
semantic acceptance keeps `product_release_ready=false`.

## Release artifact integrity

| Check | Command | Outcome |
|---|---|---|
| manifest ↔ archive consistency | `scripts/make_release.py` + 5 regression tests in `tests/test_release_packaging.py` | 162 manifest entries + `BUILD_MANIFEST.json` + 2 SBOMs = 165 archive members; SHA256SUMS has 166 lines (165 + tarball self); `sha256sum -c` → 166/166 OK |
| no circular manifest self-ref | `test_manifest_is_not_self_referenced` | **PASS** |
| no runtime data / secrets in archive | `test_manifest_policy_excludes_runtime_and_build_outputs` | **PASS** |
| manifest hashes match disk bytes | `test_manifest_declared_hashes_match_actual_file_bytes` | **PASS** |
| full manifest coverage of eligible source | `test_manifest_covers_all_eligible_source_files` | **PASS** |

## Release verdict (fresh run against the packaged candidate)

```json
{
  "status": "VALID",
  "release_ready": true,
  "product_release_ready": false,
  "blocked_scenarios": ["P09", "P12-real-model", "I05-real-model"],
  "blocked_decisions": ["P11-semantic"]
}
```

Interpretation per directive §14:

- Structural verification: **VALID** (every mandatory structural gate OK; 4 optional gates SKIPPED for the documented reasons).
- System E2E verification: **PASS** (every supported path above, run end-to-end against real uvicorn + real browser).
- Real-model verification: **NOT EXECUTED** (external prerequisite missing).
- Semantic verification: **UNRESOLVED** (product decision pending).
- Product release readiness: **FALSE** (correctly, per policy).

## Promotion authorisation

v6.0.7 is **not** authorised for production promotion. The verified candidate
is delivered as a historical artifact; promotion requires completion of the
real-model and semantic acceptance steps above, performed by an operator with
the environment and product authority to do so.
