# v6.0.6 — Codex findings reconciled + evidence-gated product readiness (2026-10-12T18:35Z)

Append-only follow-up to :file:`v6-phase12-final-reconciliation-and-adversarial.md`.

Executed under **"OneShot — Consolidated Release Reconciliation, System E2E
Hardening and Controlled Completion"**. All changes landed in an isolated
candidate workspace. The previous v6.0.5 artefacts remain as historical
evidence.

## §1 — Baseline and Codex findings reproduced

Baseline tarball: `oneshot-complete-release-2026-10-12-v6.0.5.tar.gz` SHA‑256
`be5ad53a9efa4af2119238355e3d7bacae125680fdd18b16453001e74db45e81`.

Reproduced the four Codex claims against that artefact:

| Claim | Reproduced | Mechanism |
|---|---|---|
| 168 files in tarball, all match external SHA256SUMS | ✓ | `find OneShot -type f | wc -l` == `wc -l SHA256SUMS - 1`; byte-for-byte match |
| BUILD_MANIFEST.json declares 142 entries | ✓ | `jq '.entries\|length' BUILD_MANIFEST.json` |
| 26 tarred files absent from manifest | ✓ | `comm -23 tarball_paths manifest_paths` |
| 11 declared hashes differ | ✓ | per-path join on manifest vs external SHA list |
| "Four unexpected files appear under data/" | ✓ | the 26 unmanifested files include exactly four `data/*` entries |

### Root causes

- **The shipped v6.0.1–v6.0.5 artefacts were packaged by hand** (not via
  `scripts/make_release.py`), so `BUILD_MANIFEST.json` was never regenerated
  and still reflected the v6.0 build (142 entries).
- **Manual `tar` collected runtime/build outputs** (`data/*`, `dist/*`,
  `frontend/dist/*`) that `make_release.py` would have excluded via
  `EXCLUDE_PREFIXES`.
- **`BUILD_MANIFEST.json` self-referenced** inside its own `entries[]`, which
  is a circular hash dependency (writing a new manifest changes its own
  SHA256, invalidating the previously-recorded value).

## §2 — Priority 0 — Release artifact integrity

**Code changes** (`scripts/make_release.py`):

- Added `SELF_EXCLUDE = {'BUILD_MANIFEST.json'}` and extended `_is_excluded`
  to skip it. The manifest is still packed into the archive and listed in
  `SHA256SUMS`, just not in its own `entries[]`.
- Tarball assembly explicitly adds `BUILD_MANIFEST.json` after writing it,
  so the archive always carries the fresh manifest even though the manifest
  does not list itself.
- `SHA256SUMS` emits a dedicated line for the fresh manifest right next to
  the SBOM lines.

**Policy restated:**

- Source manifest (`BUILD_MANIFEST.json`) excludes: `dist/`, `data/`,
  `frontend/dist/`, `frontend/node_modules/`, `.git/`, `__pycache__`,
  `.pytest_cache`, `.ruff_cache`, `*.egg-info`, `*.pyc`, and
  `BUILD_MANIFEST.json` itself.
- Archive = manifest entries + `BUILD_MANIFEST.json` + 2 embedded SBOMs
  under `OneShot/dist/sbom.*.cyclonedx.json`.
- External `SHA256SUMS` = tarball sha256 + per-member sha256 for every
  archive member.

**Regression test** — `tests/test_release_packaging.py` (5 tests, all green):

- `test_manifest_policy_excludes_runtime_and_build_outputs` — no `data/`,
  `dist/`, `frontend/dist/`, `__pycache__`, `*.pyc` in manifest.
- `test_manifest_is_not_self_referenced` — `BUILD_MANIFEST.json` never
  appears in its own `entries[]`.
- `test_manifest_declared_hashes_match_actual_file_bytes` — detects stale
  manifest hashes (the exact Codex finding).
- `test_manifest_covers_all_eligible_source_files` — detects new files
  added without rerunning `make_release.py`.
- `test_shipped_release_archive_matches_sha256sums` — tarball self-hash +
  per-member sha against the external SHA256SUMS.

**Observed on the rebuilt v6.0.6 artefact:**

- Archive members: **162** (159 manifest entries + BUILD_MANIFEST.json + 2
  SBOMs).
- SHA256SUMS lines: **163** (tarball self-hash + 162 members).
- Zero `data/*`, `dist/*` (except the two SBOMs), `frontend/dist/*` entries
  in the manifest.
- Zero self-reference inside BUILD_MANIFEST.
- All five packaging regression tests green.

## §3 — Priority 1 — Verifier evidence-consumption

**Code changes** (`scripts/verify_release.py` +
`scripts/receiver_realmodel_evidence.py`):

- Each required real-model scenario (`P09`, `P12-real-model`,
  `I05-real-model`) is now evaluated **independently** from its own signed
  evidence file at `data/realmodel_evidence/<scenario>.json`.
- Evidence schema fields: `scenario`, `generated_at`, `oneshot_commit`,
  `model_endpoint`, `model_name`, `job_id`, `artifact_id`,
  `artifact_sha256`, `proof` (HMAC-SHA256 over
  `scenario|commit|job_id|artifact_sha256|nonce`), `nonce`.
- Verifier refuses to mark a scenario `VERIFIED` unless:
  - the file exists AND parses as JSON,
  - every required field is present,
  - the `scenario` field matches the filename,
  - the `model_endpoint` is a loopback http(s) URL (ADR‑002),
  - the `oneshot_commit` matches the current `git rev-parse HEAD`,
  - the `proof` HMAC validates under `ONESHOT_EVIDENCE_HMAC_KEY`.
- Absent key or missing files → `PENDING_REALMODEL_RUNTIME`; present but
  malformed/stale/wrong HMAC/non-loopback endpoint → `EVIDENCE_INVALID`.
- The verifier output now carries `realmodel_scenarios_detail` with the
  exact cause classification per scenario.
- The new `scripts/receiver_realmodel_evidence.py` script generates a
  properly signed evidence file on a receiver host after an actual
  llama.cpp run.

**Regression test** — `tests/test_verify_release_evidence.py` (10 tests, all
green). Covers all seven cases named in the directive §3:

- Missing evidence does not pass.
- Malformed JSON / missing field / scenario mismatch does not pass.
- Replayed evidence (stale commit / wrong HMAC) does not pass.
- Non-loopback model endpoint does not pass.
- Each scenario evaluated independently.
- Properly signed evidence can satisfy its scenario.
- Product readiness becomes true only when every required scenario is
  `VERIFIED`.

**P11-semantic** stays `REQUIRES_PRODUCT_DECISION`; no scoring threshold or
authorisation invented. The existing `docs/P11_SEMANTIC_DECISION.md`
remains the open-questions document.

## §4 — Priority 2 — Stale task removal

Confirmed by direct inspection that the following items identified as
"existing in the shipped tree" are indeed present:

- SQLite WAL (`systems/store.py:184`), `busy_timeout` (line 230),
  `foreign_keys=ON` (line 230).
- `X-Request-ID` set in middleware (`systems/api.py:170`).
- `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'`
  (`systems/api.py:200,203`).
- UI landmarks: `<main class="system-panel" aria-label=…>`, `<nav
  id="workspace-menu" …>`, 8 `aria-live` consumers in `frontend/index.html`.
- Real-server backup/restore test
  (`tests/e2e_backup_restore.py` with `_launch` / `_ready`).

Not re-implemented.

## §5 — Priority 3 — System E2E invariants

No new E2E module was added this turn — the directive forbids inventing
coverage without a reproduced defect. The existing suite covers positive,
negative, failure, mutation-boundary and history/replay paths across
`e2e_browser`, `e2e_presend`, `e2e_prompt_workspace`,
`e2e_improvement_loop`, `e2e_improvement_loop_closure`,
`test_adversarial_fixtures`, and `test_apply_security`.

## §6 — Priority 4 — Worker-stall detection

**Code changes** (`systems/api.py`):

- New shared state `_pump_state = {last_tick_at, last_exception, started_at}`.
- `foreground_pump` updates `last_tick_at` on each successful step and stores
  the repr of any raised exception.
- New `_worker_status()` helper classifies the worker into
  `idle_healthy | active | queued_waiting | stalled | failed | disabled`
  using both the heartbeat age (default 30 s via
  `ONESHOT_WORKER_STALL_SECONDS`) and the oldest queued/running job age
  (default 120 s via `ONESHOT_QUEUED_STALL_SECONDS`).
- `/ready` now reports the worker status under `components.worker` and
  returns 503 with the worker detail when the worker is `stalled` or
  `failed`.

**Regression test** — `tests/test_ready_worker_stall.py` (3 tests, all
green):

- `test_worker_disabled_is_ready` — `auto_worker=False` → worker is
  `disabled`, `/ready` passes.
- `test_worker_idle_healthy_is_ready` — real pump ticks once, worker is
  `idle_healthy` or `active`.
- `test_queued_backlog_older_than_threshold_marks_stalled` — a real job is
  admitted via the authenticated API, its `created_at` is pinned into
  2020, `/ready` returns 503 with `components.worker == 'stalled'` and
  the exact backlog age under `worker.oldest_backlog_age_seconds`.

The directive's explicit warning — "do not implement a timestamp-only
heartbeat that falsely reports an idle or long-running worker as unhealthy"
— is satisfied: `idle_healthy` is a valid steady state, and `queued_waiting`
is a distinct non-stalled label used when a backlog exists but the pump is
alive.

## §7 — Priority 5 — Complete backup / restore

**Code changes** (`scripts/backup.py` + `tests/e2e_backup_restore.py`):

- `backup(source, target)` now also copies `applied/` with per-file sha256
  into `MANIFEST.applied[]`.
- `verify_backup(path)` verifies every `applied/` entry, refuses any
  altered byte, refuses unexpected files, and refuses the whole backup
  if the `applied/` directory went missing between backup and verify.
- `restore_to_staging(backup_dir, destination)` mirrors `applied/` into
  the fresh staging directory alongside the DB and `files/`.
- `tests/e2e_backup_restore.py` no longer manually `copytree`s
  `applied/`; the shipped `backup()` handles it under one documented
  procedure.

**Regression test** — `tests/test_backup_restore_applied.py` (5 tests, all
green):

- `test_backup_captures_applied`.
- `test_verify_backup_detects_altered_applied`.
- `test_verify_backup_detects_unexpected_applied`.
- `test_verify_backup_detects_missing_applied_dir`.
- `test_restore_mirrors_applied_into_staging`.

The real-server backup/restore E2E still passes after the change
(`tests.e2e_backup_restore` returned `BACKUP_RESTORE_E2E_PASS` on three
consecutive runs).

## §8 — Priority 6 — Additional hardening (deferred)

Only items the directive lists as "demonstrated weaknesses" were in scope.
No reproducible defect was found for: multi-user auth, horizontal scaling,
Helm/Terraform modules, distroless base, COEP, deletion policies.
Deferred without implementation.

## §9 — Independent verification matrix

| Area | Command | Result |
|---|---|---|
| Locked dep sync | `uv sync --locked --extra test` | OK |
| Python lint | `uv run --locked ruff check .` | **All checks passed!** |
| Python tests | `uv run --locked pytest` | **282 passed, 1 skipped** |
| Frontend build | `node frontend/build.mjs` | 7 assets to `frontend/dist` |
| Release packaging | `tests/test_release_packaging.py` | 5/5 green on the rebuilt v6.0.6 |
| Verifier evidence | `tests/test_verify_release_evidence.py` | 10/10 green |
| Backup/restore | `tests/test_backup_restore_applied.py` + `tests.e2e_backup_restore` | 5/5 unit + E2E green |
| Worker stall | `tests/test_ready_worker_stall.py` | 3/3 green |
| Browser E2E (incl. improvement loop + closure) | shipped harness | all green |
| `scripts/verify_release.py` | 3 consecutive runs | **VALID (structural)** · `product_release_ready: false` · blocked = `[P09, P12-real-model, I05-real-model]` |
| Real-model acceptance | needs reachable llama.cpp + `ONESHOT_EVIDENCE_HMAC_KEY` | **ENVIRONMENT BLOCKED** |
| P11-semantic | docs/P11_SEMANTIC_DECISION.md | **PRODUCT DECISION BLOCKED** |

## §10 — Final diff vs v6.0.5

**Changed:**

- `scripts/make_release.py` — SELF_EXCLUDE + separate manifest line in SHA256SUMS.
- `scripts/verify_release.py` — new evidence-consumption helpers +
  `realmodel_scenarios_detail` field in verdict output.
- `scripts/backup.py` — applied/ included in backup, verified by
  `verify_backup`, mirrored by `restore_to_staging`.
- `systems/api.py` — worker heartbeat + `/ready` worker classification.
- `tests/e2e_backup_restore.py` — remove the now-redundant manual
  copy of `applied/`.
- `tests/test_verify_release_policy.py` — one scenario renamed to reflect
  the new policy ("gate OK no longer implies scenario VERIFIED without a
  signed evidence file").
- `BUILD_MANIFEST.json` — regenerated by the fixed `make_release.py`.

**Added:**

- `scripts/receiver_realmodel_evidence.py` — receiver-side helper.
- `tests/test_release_packaging.py` — 5 new regression tests.
- `tests/test_verify_release_evidence.py` — 10 new regression tests.
- `tests/test_backup_restore_applied.py` — 5 new regression tests.
- `tests/test_ready_worker_stall.py` — 3 new regression tests.
- `docs/phase_records/v6-phase13-codex-reconciliation.md` — this record.

**Removed:** none. Historical files and evidence preserved.

## §11 — Deliverables

- `dist/oneshot-complete-release-2026-10-12-v6.0.6.tar.gz` — SHA-256 captured in
  the attached SHA256SUMS file.
- `dist/oneshot-complete-release-2026-10-12-v6.0.6-SHA256SUMS.txt` — 163 lines.
- `/work/verify_release_last_run_v6.0.6.json` — verifier output.
- `/work/oneshot-complete-release-2026-10-12-v6.0.6.zip` — downloadable bundle
  (tarball + SHA256SUMS + verdict JSON).

The v6.0.5 artefacts are preserved as historical evidence; the active
`/OneShot/` tree is NOT overwritten.

## §12 — Final verdict

| Scenario | State |
|---|---|
| P01–P08, P10, P11-structural, P14, P18 (incl. a/b) | **VERIFIED** (contract, API, browser) |
| P09, P12-real-model, I05-real-model | **ENVIRONMENT BLOCKED** (no llama.cpp runtime; verifier now requires signed evidence file) |
| P11-semantic | **PRODUCT DECISION BLOCKED** (docs/P11_SEMANTIC_DECISION.md) |
| I01–I04, I06–I15, I16 (incl. fresh-context + restart) | **VERIFIED** |

**Overall release verdict:**
`NOT VALID — MANDATORY ACCEPTANCE INCOMPLETE OR FAILED`.

Blocked scenarios: `['P09', 'P12-real-model', 'I05-real-model']`
(`ENVIRONMENT BLOCKED`); `P11-semantic` (`PRODUCT DECISION BLOCKED`).

Promotion to production is **not authorised**. The verifier's structural
`VALID` and `release_ready=true` reflect only the executable mandatory
non-model E2E paths; `product_release_ready=false` is the authoritative
product boundary.
