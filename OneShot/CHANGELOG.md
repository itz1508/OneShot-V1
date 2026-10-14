# Changelog

All notable changes to OneShot are recorded here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased] — 2026-10-11 (WP-00..WP-09 + M-00/M-01 pass)

### Added

- `scripts/verify_release.py` — now computes the release verdict from executed evidence instead of unconditionally emitting NOT_VALID. Mandatory gate failures (`ruff_lint`, `python_diagnostics`, `workflow_conformance`, `frontend_check`, `frontend_tests`, `frontend_build`, `http_integration`, `multi_provider_protocol`, `chromium_install`, `browser_integrated_e2e`, `browser_presend_e2e`, `selfcheck`, `locked_python_environment`) demote to `NOT_VALID` with the exact failing gate IDs. Optional gates (`docker_*`, `live_model_browser_e2e`) report `SKIPPED_PREREQUISITE_MISSING` with the exact missing binary or env var and do NOT demote the verdict.
- `tests/test_verify_release.py` — proves both the honest VALID and honest NOT_VALID verdict paths.
- `scripts/winml_feasibility.py` + `docs/WINML_FEASIBILITY.md` + `tests/test_winml_feasibility.py` — M-00/M-01 read-only probe. On non-Windows hosts reports `TOOL_MISSING` / `PREREQUISITE_MISSING` and the exact next step; never installs `winml-cli` and keeps it out of `pyproject.toml`. `data/winml/feasibility.json` records host, policy and the recorded M-00 decision (currently `UNRESOLVED`).
- `GET /ready` — readiness probe (storage AND file_store AND frontend ok); `/health` keeps backward-compatible `{"ok":true}` body plus `components` detail.
- `capabilities/catalog.py` — auto-discovery for `/api/capabilities`; preserves the pkg-specific `model` + `agent_integrations` top-level keys; adds a `catalog` field with per-tool description and availability.
- Attribute docstrings on every `systems/contracts.py` field + `use_attribute_docstrings=True` on the base `Contract`. `/openapi.json` now carries per-field descriptions. `tests/test_contracts_documented.py` fails the build if a future PR adds an undocumented field.
- `frontend/lifecycle.js` + `frontend/tests/lifecycle.test.mjs` + `frontend/tests/visual_states.test.mjs` — framework-free `useReducer`-shaped UI lifecycle reducer with Pause-requires-backend-confirmation; one reducer-snapshot per named screen (6 screens).
- `docs/UI_LIFECYCLE.md`, `docs/WORKFLOWS.md`, `docs/TRACING.md` — pins to live file:symbol pairs; `tests/test_workflow_conformance.py` locks the mapping.
- `tests/test_tracing_filters.py`, `tests/test_security_headers.py`, `tests/test_ready_endpoint.py`, `tests/test_capabilities_catalog.py` — explicit behavioral coverage of the hardening additions.
- `Referrer-Policy: no-referrer` + `Permissions-Policy` deny-list on every HTTP response.
- `FileStore.sanity()` round-trip probe (used by `/health`, `/ready`, and `scripts/selfcheck.py`).
- `GET /api/conversations/{cid}/events` server-side filters: `job_id`, `kind`, `node_id`, `since`, `until`.
- `GET /api/conversations/{cid}/jobs/{jid}/latest` — most-recent-event lookup; the companion `trace()` projection reports `started_at`, `ended_at`, and `duration_ms` per node when both ends exist.
- `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`, `.gitattributes`, `.pre-commit-config.yaml`, `.github/workflows/ci.yml`, `Makefile`.
- `uv.lock` committed (resolved on Python 3.11.17).

### Fixed

- `scripts/verify_release.py` previously appended an unconditional `BLOCKED` entry and always returned exit 1. The replaced script is now evidence-derived (WP-01). As of v5.4 every non-OK gate also carries a `Root Cause / Analyze / Causing / Analyzing` diagnostic tag with an explicit cause class, missing prerequisite, and corrective action (see `systems/diagnostic_tags.py`).
- `tests/e2e_browser.py` strict-mode violation when the UI gained a `Remove requirements.md` button — switched source selector to `exact=True`.
- `tests/e2e_presend.py` false negative when a `<pre>` preserved trailing whitespace — switched the two `inner_text()` reads to `text_content()`.
- Frontend layout: at 1440×900 Chromium viewport, `.source-items` overflowed vertically and `.source-library` intercepted pointer events on the active source button. Bounded `.source-items` min-height, made `.scope-actions` / `.context-preview` scroll internally.
- `B904` chained-exception warnings in `systems/api.py` and `systems/operations.py` (via `raise ... from None` / `from e`).
- Dead imports in `systems/api.py`, `systems/operations.py`, `systems/auto_generator/generator.py`.
- `tests/test_workflow.py::test_api_auth_and_security` relaxed `{"ok":True}` to `.get('ok') is True` after `/health` grew the backward-compatible `components` key.

### Changed

- `pyproject.toml`: ruff lint configured for correctness-only (F, B, UP, SIM) with the shipped style exceptions. Dependencies unchanged.
- `/api/capabilities` now reads from `capabilities.catalog`; the response is a strict superset of the previous pkg shape (every pre-existing key preserved; `catalog` added).
- `/health` response body is a strict superset (`ok:true` plus `components`).

### Security

- `Referrer-Policy: no-referrer` and `Permissions-Policy` deny-list on every HTTP response.
- `pip-audit` and `npm audit --omit=dev --audit-level=high` reported **0 known vulnerabilities** at release.

## [Unreleased] — 2026-10-11

### Added

- `GET /ready` — readiness probe distinct from the `/health` liveness probe; returns 200 only when storage, FileStore sanity, and the frontend build on disk are all `ok`. `tests/test_ready_endpoint.py` covers the 200 and 503 branches.
- `capabilities/catalog.py` — auto-discovered capability-tool catalogue; `/api/capabilities` now reads from it. The response is a strict superset of the previous hand-maintained shape (every existing top-level key preserved) and adds a `catalog` key with per-tool description + availability. `tests/test_capabilities_catalog.py` locks both shapes.
- `frontend/tests/visual_states.test.mjs` — one reducer-snapshot test per named screen (`SourceManagement`, `Starting`, `ProcessDisplay`, `Pausing`, `Paused`, `EditorReview`) + a transition-table integrity test. Applies the react.dev "mock every state" recipe without introducing React.
- `#evidence-mode-banner` in `frontend/index.html` + `renderEvidenceMode()` in `frontend/app.js` — reads `/api/capabilities` on connect and reveals a one-line banner when `auto_generator.provider === 'evidence'`.
- `withPending(button, action)` + `data-pending` wiring in `frontend/app.js` — the UI-side half of the duplicate-submission guard on `#login-submit`, `#save-draft`, `#start-review-confirm`, and `#presend-approve`. Pairs with the server-side `MessageCreate` / `JobCreate` idempotency keys to deduplicate across uncertain network retries at both boundaries.
- Attribute docstrings on every `systems/contracts.py` field + `use_attribute_docstrings=True` on the base `Contract`. `/openapi.json` now carries human descriptions. `tests/test_contracts_documented.py` fails the build if a future PR adds an undocumented field.
- `tests/test_tracing_filters.py::test_events_since_until_time_window_filters_real_events` — exercises the shipped `since`/`until` parameters against real worker-emitted events.
- `docs/UI_LIFECYCLE.md §7` — the React modernization decision anchor, with the real-tree comparison (same reducer shape, no bundler, same E2E coverage).
- `docs/TRACING.md` — pins the event / span data model, the attribute-naming policy, and the operator playbook. Mirrors the implemented endpoints exactly.
- `docs/UI_LIFECYCLE.md` — pins the implemented `frontend/lifecycle.js` reducer and documents the React Hooks equivalence.
- `docs/WORKFLOWS.md` — anchors D-01..D-08 to live file:symbol pairs; `tests/test_workflow_conformance.py` locks the mapping.
- `frontend/lifecycle.js` + `frontend/tests/lifecycle.test.mjs` — framework-free `useReducer`-shaped UI lifecycle with Pause-requires-backend-confirmation.
- `scripts/selfcheck.py` + `make selfcheck` — offline component check (storage, file_store, frontend build).
- `/api/conversations/{cid}/jobs/{jid}/latest` — most-recent-event lookup.
- `GET /api/conversations/{cid}/events` server-side filters: `job_id`, `kind`, `node_id`, `since`, `until`.
- `trace()` now reports per-node `started_at`, `ended_at`, and `duration_ms` when both ends are present.
- `Referrer-Policy: no-referrer` and `Permissions-Policy` deny-list on every HTTP response.
- `FileStore.sanity()` round-trip probe (used by `/health` and `scripts/selfcheck.py`).
- `/health` now reports per-component status (`storage`, `file_store`, `frontend`) while keeping the backward-compatible `{"ok": true}` body on success.
- `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`, `LICENSE`, `.gitattributes`.
- Workflow conformance now includes D-H (UI lifecycle) anchors.

### Changed

- Docs rewritten so every file describes implemented behaviour; "candidate / future / pending / planning" phrasing removed.
- `frontend/package.json` extended with `description`, `license`, `repository`, `keywords`, `author`, `devDependencies`, and `scripts.{lint,audit}`; `check` and `lint` include the new `lifecycle.js`.
- `frontend/build.mjs` now copies `lifecycle.js` into `frontend/dist`.

### Fixed

- `B904` chained exceptions in `systems/api.py` and `systems/operations.py` now use `raise ... from None` / `from e` as appropriate.
- Dead imports removed from `systems/api.py` and `systems/operations.py`.
- E2E tests tolerate the SSE keepalive by waiting on `domcontentloaded` + explicit selectors instead of `networkidle`.

### Security

- Added `Referrer-Policy: no-referrer` and `Permissions-Policy` (camera, microphone, geolocation, payment, usb, interest-cohort all `()`).
- Documented the single-operator threat model and the dependency-audit gates in `SECURITY.md`.
- `pip-audit` and `npm audit --omit=dev --audit-level=high` reported **0 known vulnerabilities** at the time of release.

## [0.3.0] — baseline

Initial published tree: 86 files, D-01..D-08 workflows implemented, SSE event stream, SQLite-backed background evaluator (`proposal_only`), hash-verified Apply boundary. Full inventory in `BUILD_MANIFEST.json`.

## [v6.0.7] — 2026-10-12 — Controlled correction of v6.0.6 verification gaps

- Evidence authenticity (§1): verifier opens receiver's local SQLite as a second
  channel, recomputes artifact bytes, enforces scenario-operation mapping, and
  rejects nonce replay.
- Portable release identity (§2): `_release_identity` falls back to
  `BUILD_MANIFEST.host.git_sha` when `.git` is absent; empty identity fails closed.
- P11-semantic enforcement (§3): mandatory product-decision sentinel policy added;
  `product_release_ready` is false until `docs/product_decisions/P11-semantic.resolved.json`
  is written with the required fields.
- Worker-stall and lifecycle E2E (§4): long-running inference, hung execution,
  task-termination state surface, pending-work with disabled worker, startup / restart
  / shutdown transitions.
- Backup security + restored readback (§5): manifest traversal / absolute-path /
  planted-symlink refusals, authenticated HTTP readback from a restored instance,
  independence after original source deletion.

## [v6.0.8] — 2026-10-12 — Full System E2E verification run (docs only)

- Added `docs/E2E_MATRIX.md` cross-referencing every mandatory E-case to its executable suite.
- Added `docs/phase_records/v6-phase15-full-e2e-verification.md` recording the executed outcomes.
- No source changes. v6.0.7's corrections remain intact.
- 305 pytest passed; 9 end-to-end suites passed (real uvicorn + real Chromium + real HTTP); 2 real-model-dependent suites correctly refused to run without the external runtime.
- Verifier verdict unchanged: structural VALID, product_release_ready=false, blocked_scenarios=[P09, P12-real-model, I05-real-model], blocked_decisions=[P11-semantic].

## [v6.0.9] — 2026-10-12 — Comprehensive audit; single dead-code fix

- `scripts/backup.py:98` — removed dead `if False` ternary in applied-path validation; behavior unchanged, regression covered by `tests/test_backup_restore_applied.py` (10 cases).
- `docs/phase_records/v6-phase16-comprehensive-audit.md` — append-only audit record: 164 files scanned, 2 vulture findings reviewed (1 fixed, 1 false positive), 0 renames needed, 0 duplicates consolidated, 305/305 pytest, product_release_ready unchanged.
- No API / schema / event / dependency changes.

## [v6.0.10] — 2026-10-12 — Dead-code cleanup + market-practice hardening

### Fixed
- `scripts/backup.py` — removed orphaned `import pathlib` left by v6.0.9 L01 fix (RV01).
- `scripts/smoke_http.py` — restart assertion now permits background-evaluator events (shipped v6 phase 0) while preserving pre-restart event order (S01).

### Changed
- `Dockerfile` — added `HEALTHCHECK` probing `/ready` so standalone `docker run` surfaces readiness (G2).
- `compose.yaml` — added `security_opt: no-new-privileges:true` + `cap_drop: ALL` (G1, Docker CIS 5.22 / 5.25 best practice).

### Added
- `tests/test_compose_security_hardening.py` — 4 regression tests pinning HEALTHCHECK + no-new-privileges + cap_drop + read_only/tmpfs so future drift is caught.
- `docs/phase_records/v6-phase17-deadcode-and-market-gap.md` — audit record of the dead-code + market-gap pass and the 9 independent E2E suites verified against the modified source.

### Preserved
- Every supported System E2E suite passes end-to-end (305 pytest + 9 e2e_* + 57 frontend tests). Zero API / schema / event / dependency changes. `product_release_ready` remains `false` (external prerequisites unchanged).

## [v6.0.11] — 2026-10-13 — Final remaining-work ledger closure

### Added
- `.github/workflows/ci.yml` — `e2e` job now runs the three remaining System E2E suites (`tests.e2e_prompt_workspace`, `tests.e2e_improvement_loop`, `tests.e2e_improvement_loop_closure`), plus `timeout-minutes: 30` to bound stuck Playwright runs (C-01).
- `README.md` — cross-references `docs/E2E_MATRIX.md` in the "Integrated diagnostics" paragraph (D-01).
- `tests/test_ci_e2e_contract.py` — 3 regression tests pinning every runtime-independent E2E suite in CI and ensuring the two external-prerequisite suites (`e2e_live_model`, `e2e_vision_local`) stay out of deterministic CI.
- `tests/test_docs_cross_references.py` — 3 regression tests pinning the five README → docs links.
- `docs/phase_records/v6-phase18-remaining-work-closure.md` — append-only ledger of the Phase-0 reconciliation (S-02 already done; M-01/O-01 deferred; M-02 rejected; M-03 kept) and the two applied changes.

### Preserved
- No API / schema / event / dependency / UI code changes. Rate-limit bucket key (previously proposed as S-02) was already shipping as `ip:{ip}|sess:{session_cookie[:16]}` in `systems/api.py:182` — recorded as DONE.
- `product_release_ready` remains `false` — B-01 (real-model), B-02 (P11-semantic), B-03 (vision) are external prerequisites outside the agent's authority.
