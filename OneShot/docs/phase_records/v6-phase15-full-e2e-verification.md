# v6.0.8 — Full System E2E verification run (2026-10-12T20:35Z)

Append-only follow-up to :file:`v6-phase14-controlled-correction.md`.

Executed under **"OneShot — Complete System End-to-End Implementation and
Verification"**. The directive required:

1. Preserve v6.0.7's accepted functionality and demonstrated corrections.
2. Not repeat already-completed implementations.
3. Not add frameworks or new agent ownership.
4. Execute the full relevant regression suite from the exact tested source.
5. Report an honest status with explicit remaining blockers.

## Executed this turn

### Environment reconstitution

- Extracted v6.0.7 tarball (`603b2593…02ad9`) into `/tmp/v608/OneShot`.
- Installed uv 0.13.0, Node v20.20.2, Python 3.11.17.
- `UV_PROJECT_ENVIRONMENT=/tmp/uv-env uv sync --locked --extra test --python 3.11` → OK (109 wheels).
- `cd frontend && node build.mjs` → `Built 7 static assets to frontend/dist`.
- `uv run --locked python -m playwright install --with-deps chromium` → OK (Chromium 153 + system libs).

### Pytest full suite (fresh install)

```
================== 305 passed, 2 skipped, 1 warning in 43.41s ==================
```

Zero regressions vs the v6.0.7 phase-14 record.

### End-to-end suites (independently executed)

| Suite | Outcome | Notes |
|---|---|---|
| `tests.e2e_http` | PASS | `apply=verified readback, artifact=evidence_packet, auth=cookie+csrf, http=observed, job=real worker, restart=durable state, source=immutable, sse=observed` |
| `tests.e2e_multi_provider_http` | PASS | `agent_messages=2, apply_readback=true, artifact_kind=model_generated, protocol_requests=3, restart_persistence=true, stored_events=23, worker_completed=true` |
| `tests.e2e_backup_restore` | PASS | `applied_sha256 == restored_sha256` (`b045daf7…c9bb`), real uvicorn, result=`BACKUP_RESTORE_E2E_PASS` |
| `tests.e2e_live_model_local` | PASS | local Ollama protocol stub on 127.0.0.1; `provider=ollama, actual_worker_events=4, token_preserved=true, result=LIVE_MODEL_LOCAL_E2E_PASS` |
| `tests.e2e_browser` | PASS | Chromium + real uvicorn; `apply_verified=true, authentication=cookie+csrf enforced, restart_persistence=true, uninstalled_agent_blocked=true, result=E2E_SLICE_OBSERVED` |
| `tests.e2e_presend` | PASS | `PRESEND_BROWSER_E2E_PASS cancel=0 approved_exact=1 original_preserved=1 direct_send=1` |
| `tests.e2e_prompt_workspace` | PASS | 10 scenarios: P01, P02-uvicorn-restart, P03, P04, P05, P08, P10, P11, P12-precondition-missing, P18 |
| `tests.e2e_improvement_loop` | PASS | 9 scenarios: I03-review-create/update, I06-eval-propose-approve, I07-eval-reject, I08-eval-run-after-approve, I10-proposal-lifecycle, I11-no-apply-mutation, I14-run-history-navigation, I15-review-survives-restart |
| `tests.e2e_improvement_loop_closure` | PASS | 5 scenarios: I09-recurring-defects, I12-baseline-candidate-compare, I13-prompt-version-immutable, I16-full-lifecycle, I16-fresh-context-and-restart |
| `tests.e2e_live_model` | **REFUSED** (correct) | `AssertionError: Live-model E2E requires ONESHOT_PROVIDER=openai\|gemini\|ollama\|model; evidence mode or a controlled responder is not a real model test` — the suite enforces the directive §6 rule. |
| `tests.e2e_vision_local` | **PREREQUISITE_MISSING** (correct) | needs `ONESHOT_VISION_PROVIDER=llama + ONESHOT_VISION_ENDPOINT + ONESHOT_VISION_MODEL`. |

Nine real E2E suites passed end-to-end against real HTTP / real browser / real
protocol stubs. Two real-model-dependent suites explicitly refused to run
without their external prerequisites. This is exactly the directive-§6
contract: synthetic responders cannot elevate to real-model acceptance.

### Linting / packaging

- `ruff check .` → All checks passed!
- `scripts.selfcheck` → components storage, file_store, frontend all `ok`.
- `scripts.make_release.py` → regenerates manifest; `sha256sum -c` → 166/166 OK.

### Verifier verdict (fresh run against packaged candidate)

```json
{
  "status": "VALID",
  "release_ready": true,
  "product_release_ready": false,
  "blocked_scenarios": ["P09", "P12-real-model", "I05-real-model"],
  "blocked_decisions": ["P11-semantic"]
}
```

## Added this turn (preserves accepted functionality — no code changes)

Only two documentation files added vs v6.0.7:

- `docs/E2E_MATRIX.md` — comprehensive table of every mandatory E-case, its executable suite, how to run it, and the observed outcome. Fulfills directive §16 point 7 ("E2E test matrix and fixtures").
- `docs/phase_records/v6-phase15-full-e2e-verification.md` — this file.

No code was modified. The directive explicitly says "Do not repeat already
completed implementations" and "Preserve accepted functionality, existing
contracts and demonstrated corrections." v6.0.7's five §1–§5 corrections and
every regression test it added remain intact.

## Remaining blockers (honest, unchanged)

- **Real-model acceptance.** P09 / P12-real-model / I05-real-model each need a
  reachable llama.cpp (or explicitly approved hosted provider), the
  `ONESHOT_EVIDENCE_HMAC_KEY` secret, and the receiver command to be run on the
  host that executed the scenario. Agent-side changes alone cannot clear this.
- **P11-semantic product decision.** Four open questions in
  `docs/P11_SEMANTIC_DECISION.md`. Resolution requires a human decision writer
  to drop `docs/product_decisions/P11-semantic.resolved.json` with the
  documented fields.
- **Vision-local E2E.** Needs `ONESHOT_VISION_*` env + vision-capable GGUF.

## Status

- `product_release_ready = false` — authoritative; remains false per policy.
- v6.0.6 preserved as historical evidence.
- v6.0.7 preserved as the previous controlled correction candidate.
- v6.0.8 = v6.0.7 source + documentation additions above. **No code changed.**
- Not authorised for production promotion.
