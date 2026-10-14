# v6 Phase 8 reverification — reconstituted sandbox (2026-10-12T03:40Z)

Append-only follow-up to :file:`v6-phase8-closure.md`, written after a clean
reconstitution from `oneshot-complete-release-2026-10-12-v6.0.tar.gz`
(SHA-256 `bfd6f4c191ebb12d6ad874f457d0c1ef9b5127774a53fda0235ece5fd29723b7`)
in a fresh sandbox.

## Environment

- Python 3.11.17 via uv 0.13.0.
- Node.js 20.20.2 (NodeSource) + npm 10.8.2 installed to satisfy the `node`
  / `npm` mandatory gates and the frontend `build.mjs` (top-level `await`
  requires Node ≥ 14; previous apt default was 12.22.9).
- Playwright 1.63.0 Chromium with system libraries installed via
  `playwright install --with-deps chromium`.
- No local LLM runtime, no Docker, no hosted-provider credentials — three
  optional gates (`docker_compose_config`, `live_model_browser_e2e`,
  `vision_local_e2e`) correctly stay `SKIPPED_PREREQUISITE_MISSING` with the
  explicit missing-prerequisite strings the v5.4 diagnostic vocabulary
  records.

## Reproducibility

- `uv run --locked pytest` → **226 passed, 1 skipped** (`test_llama_provider`
  skip when no local llama-server; identical skip in the v6.0 build record).
- `uv run --locked ruff check .` → `All checks passed!`.
- `uv run --locked python scripts/verify_release.py` →
  `VALID — all mandatory gates passed`, 24 mandatory OK, 3 optional skipped,
  27 gates total. Confirmed over three consecutive invocations.

## Flake observed and classified

The very first full `verify_release.py` after Playwright system-deps install
reported `NOT_VALID — mandatory failures: ['browser_presend_e2e']`. The
captured gate record carried
`AssertionError: {'status': 404, 'data': {'detail': 'Conversation not found'}}`
on line 39 of `tests/e2e_presend.py`, where the browser reads
`sessionStorage['oneshot_conversation_id']` immediately after login and
queries `/api/conversations/{cid}`.

The scenario did not reproduce: three subsequent full `verify_release.py`
runs all returned `VALID`, and a standalone invocation of
`uv run --locked python -m tests.e2e_presend` printed
`PRESEND_BROWSER_E2E_PASS` immediately before and after that run.

Classification: **transient browser race**, not a product defect. The
conversation ID is written to `sessionStorage` from an API round-trip right
after `#login-submit`; occasional first-paint races against an immediate
`sessionStorage.getItem` call. Recommended follow-up (not applied here, to
keep the scope strictly a reverification): add a `page.wait_for_function` or
`page.locator('[data-conversation-id]').wait_for()` guard before the first
`ui_api(page,path)` call — the fix is in-test, in-scope for a receiver, and
does not change any System behavior.

## Scope preserved

No source file was modified. The reconstituted tree matches the attached
v6.0 release artifact byte-for-byte (`SHA256SUMS` lines verified for
`oneshot-complete-release-2026-10-12-v6.0.tar.gz`). All acceptance evidence
in this record was produced by executing the shipped `scripts/verify_release.py`
and the shipped test modules unchanged.

## Verdict

Reverification confirms the standing v6.0 verdict:

- **Gate-level**: `VALID` (24 mandatory OK, 3 optional skipped).
- **Prompt Lifecycle E2E**: the `prompt_workspace_e2e` module returns
  `{"ok": true, "scenarios": ["P01","P02-uvicorn-restart","P03","P04","P05",
  "P08","P10","P11","P12-precondition-missing","P18"]}`, matching the
  v5.4 scoreboard.
- **Model-dependent scenarios**: P09 and the vision axis of P12 remain
  `E2E_NOT_EXECUTED / MODEL_RUNTIME_UNAVAILABLE` because no local llama-server
  or hosted-provider credentials are configured; the optional-skipped records
  carry the exact missing-prerequisite strings.
- **Overall**: unchanged — `NOT VALID — REQUIRED PROMPT LIFECYCLE E2E
  INCOMPLETE OR FAILED` on the `MODEL_RUNTIME_UNAVAILABLE` axis for P09 and
  P12-vision. The System-owned Improvement Loop additions (reviews,
  evaluations, proposals, recurring-defect summary) remain backend-complete
  and backend-tested; browser click-through for the review/evaluation/proposal
  flow is still absent.

## Evidence files

- `/work/verify_release_last_run_v6.0_rerun_2026-10-12T0335Z.json` — gate
  record of the final reverification run copied out of
  `data/verification/last_run.json`.
- All test commands and their complete stdout/stderr tails are present in
  that JSON per-gate record under `stdout_tail` / `stderr_tail`.
