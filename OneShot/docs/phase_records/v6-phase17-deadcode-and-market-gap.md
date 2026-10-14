# v6.0.10 — Dead-code cleanup + market-practice gap analysis + full E2E sweep (2026-10-12T23:40Z)

Append-only follow-up to :file:`v6-phase16-comprehensive-audit.md`.

Executed under the operator directive: *"before export, fix and remove all
dead code, and run gap analysis this build against best market practice, test
each workflow e2e independently before provide download."*

## Pass A — Dead-code audit (findings)

Scanners used: `ruff==0.14.0` (F rules), `vulture==2.14` at thresholds 60 / 70 / 80 / 100%.

| ID | Finding | Severity | Action |
|---|---|---|---|
| **RV01** | `scripts/backup.py:1` — `import pathlib` orphaned after v6.0.9 L01 fix (`pathlib.<name>` has 0 references in file; `from pathlib import Path` on line 6 is the active import) | COSMETIC | **FIX** — remove the orphaned import |
| L02 | `capabilities/researcher/tools/web_extraction.py:5` — `attrs` unused in `handle_starttag(tag, attrs)` | IGNORE (false positive) | KEEP — stdlib HTMLParser signature |
| Vulture 60% confidence FastAPI route handlers | FastAPI decorators register functions as endpoints; vulture cannot see the registration | IGNORE | KEEP |
| Vulture 60% confidence Pydantic validators | `@model_validator` methods are invoked by Pydantic framework | IGNORE | KEEP |
| Ruff F405 star imports in `tests/test_contracts.py` | Project's `ruff` config explicitly ignores F403/F405 for tests | IGNORE | KEEP |

**Only RV01 is a real finding. Everything else is a scanner false positive against the project's accepted patterns.**

## Pass A — Market-practice gap analysis

Benchmarked against: OWASP ASVS 5.0, NIST SP 800-218 SSDF, Docker security hardening (CIS Benchmarks), Google Cloud security best practices for containerized workloads.

Already present (verified in source):

| Practice | Implementation |
|---|---|
| HttpOnly + SameSite=Strict + Secure cookies | `systems/api.py:155` |
| CSP + HSTS + nosniff + frame-ancestors deny | `systems/api.py:206-214` |
| CSP violation reporting endpoint | `systems/api.py:258-265` |
| Rate limiting with token-bucket + 429 + Retry-After | `systems/api.py:85-101` |
| X-Request-Id correlation middleware | `systems/api.py:175-194` |
| CSRF via x-oneshot-csrf header + session cookie | `systems/api.py:153-170` |
| Prometheus /metrics endpoint | `systems/api.py:234` |
| Structured logger namespaces | `systems/api.py`, `systems/background.py` |
| Request size + per-source + combined scope limits | `systems/operations.py:140,258` |
| SBOMs for both Python + frontend (CycloneDX) | `dist/sbom.*.cyclonedx.json` |
| Docker multi-stage build + non-root user (uid 10001) | `Dockerfile:22-23` |
| compose.yaml `read_only: true` + tmpfs | `compose.yaml` |
| compose.yaml healthcheck probing /ready | `compose.yaml` |
| Locked dependencies (uv.lock + package-lock.json) | present |
| Loopback-only bind in compose | `compose.yaml ports: "127.0.0.1:8787:8787"` |

Gaps identified (minor hardening):

| ID | Gap | Severity | Action |
|---|---|---|---|
| **G1** | `compose.yaml` lacks `security_opt: no-new-privileges:true` + `cap_drop: ALL` (Docker CIS 5.22 / 5.25) | MINOR | **FIX** |
| **G2** | `Dockerfile` lacks `HEALTHCHECK` instruction (image-standalone, independent of compose) | MINOR | **FIX** |
| G3 | `pyproject.toml` lacks `license`, `classifiers`, `urls` metadata | COSMETIC | DEFER (not a security/correctness item; project is private) |
| G4 | No MFA / distroless / OTel exporter / signing infra | — | REJECTED by prior directives (§8) — these are speculative, not required by the single-operator deployment profile |

## Pass A — Shipped operator probe check

| Script | Status |
|---|---|
| `scripts/smoke_http.py` | **FAIL** on v6.0.9: asserts `len(events) == len(ev)` across restart; background evaluator (shipped v6 phase 0) appends 3 advisory `background_*` events after job completion. Pre-existing issue, not a v6.0.9 regression. |

| ID | Severity | Action |
|---|---|---|
| **S01** | COSMETIC — operator probe only, not in pytest suite. Fix: relax strict equality to `len(post) >= len(pre)` + preserve pre-order. | **FIX** |

## Pass B — Controlled corrections

Four atomic fixes applied:

| Fix | File | Lines |
|---|---|---|
| RV01 | `scripts/backup.py` | -1 line (remove orphaned `import pathlib`) |
| G1 | `compose.yaml` | +4 lines (`security_opt`, `cap_drop`) |
| G2 | `Dockerfile` | +2 lines (HEALTHCHECK instruction) |
| S01 | `scripts/smoke_http.py` | +5 lines (relaxed restart event comparison, preserve order) |

Plus one regression test:

- `tests/test_compose_security_hardening.py` — 4 tests pinning HEALTHCHECK + `no-new-privileges` + `cap_drop: ALL` + `read_only/tmpfs` so future drift is caught.

**Zero** changes to API routes, schemas, event kinds, UI, or Python/JS dependencies.

## Pass B — E2E workflow matrix (nine suites run independently)

Each supported System E2E executed as a separate `python -m tests.e2e_*` invocation against the modified source:

| ID | Suite | Outcome |
|---|---|---|
| E01 | `tests.e2e_http` | **PASS** — real uvicorn, cookie+csrf, SSE, Apply readback, restart durability |
| E02 | `tests.e2e_multi_provider_http` | **PASS** — 3 protocol requests, apply_readback=true, restart_persistence=true, stored_events=23 |
| E03 | `tests.e2e_backup_restore` | **PASS** — `applied_sha256 == restored_sha256` byte-equal; result `BACKUP_RESTORE_E2E_PASS` |
| E04 | `tests.e2e_browser` | **PASS** — real Chromium + real uvicorn; apply_verified=true, uninstalled_agent_blocked=true |
| E05 | `tests.e2e_presend` | **PASS** — approved_exact=1 original_preserved=1 direct_send=1 cancel=0 |
| E06 | `tests.e2e_prompt_workspace` | **PASS** — 10 scenarios (P01, P02-uvicorn-restart, P03, P04, P05, P08, P10, P11, P12-precondition-missing, P18) |
| E07 | `tests.e2e_improvement_loop` | **PASS** — 9 scenarios (I03/I06/I07/I08/I10/I11/I14/I15, two I03 shapes) |
| E08 | `tests.e2e_improvement_loop_closure` | **PASS** — 5 scenarios (I09/I12/I13, two I16 shapes) |
| E09 | `tests.e2e_live_model_local` | **PASS** — local Ollama protocol stub, `provider=ollama`, result `LIVE_MODEL_LOCAL_E2E_PASS` |

Plus operator diagnostics:
- `scripts/smoke_http.py` — **PASS** (after S01 fix)
- `scripts/selfcheck.py` — **PASS** (storage/file_store/frontend all `ok`)
- `scripts/benchmark_background.py` — **PASS**
- `scripts/docker_smoke.py` — `SKIPPED_PREREQUISITE_MISSING` (docker CLI not in sandbox; expected)

Full pytest: **307 collected, 305 passed, 2 skipped, 0 failed** after regenerating `BUILD_MANIFEST.json`.

Frontend unit tests: `node --test frontend/tests/*.test.mjs` → **57 pass, 0 fail**.

Lint: `ruff check .` → **All checks passed!**

Vulture: 0 confirmed findings; only the HTMLParser signature false positive remains.

## Pass B — Not-executed real-model acceptance (unchanged)

- P09 / P12-real-model / I05-real-model: `PENDING_REALMODEL_RUNTIME` (external prerequisite missing: no llama.cpp, no `ONESHOT_EVIDENCE_HMAC_KEY`).
- P11-semantic: `UNRESOLVED` (product decision pending).

Per directive scope: **do not fabricate real-model execution** when the authorized runtime is unavailable.

## Final status

- Structural verification: **VALID**
- System E2E verification: **PASS** (9 independent suites + full pytest 305/305)
- Market-practice posture: **IMPROVED** (G1 + G2 added; G3/G4 explicitly deferred/rejected)
- Dead code: **CLEANED** (RV01 fixed; all other scanner findings are confirmed false positives)
- Real-model verification: **NOT EXECUTED** (external prerequisite missing)
- Semantic verification: **UNRESOLVED** (product decision pending)
- `product_release_ready = false` — unchanged
- Promotion to production: **not authorised**
- v6.0.6 / v6.0.7 / v6.0.8 / v6.0.9 preserved as historical evidence

Per release policy: v6.0.10 is issued because four genuine source changes were applied (RV01 dead-code + G1 compose hardening + G2 Dockerfile healthcheck + S01 smoke-probe fix) with one new regression test.
