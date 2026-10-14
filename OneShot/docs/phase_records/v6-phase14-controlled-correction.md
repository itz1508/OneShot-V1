# v6.0.7 — Controlled correction of v6.0.6 verification gaps (2026-10-12T20:00Z)

Append-only follow-up to :file:`v6-phase13-codex-reconciliation.md`.

Executed under **"OneShot v6.0.7 — Authorized Final Evidence and E2E Correction"**.
Preserves v6.0.6 unchanged as historical evidence; v6.0.7 is a narrow correction
that lands only the five remaining gaps the preceding turn identified. No
roadmap restart, no new framework, no reimplementation of previously verified
functionality.

## Scope

| § | Gap closed | Shipping artefacts |
|---|---|---|
| §1 | Real-model evidence authenticity: HMAC-valid JSON alone cannot establish PASS | `scripts/verify_release.py` _load_evidence + _verify_artifact_second_channel + nonce ledger; `scripts/receiver_realmodel_evidence.py` scenario-aware sha; `tests/test_verify_release_evidence.py` nonce-replay + fabricated-artifact + scenario-operation-mismatch tests |
| §2 | Portable release identity (no `.git` required) | `scripts/verify_release.py::_release_identity` falls back to `BUILD_MANIFEST.host.git_sha`; fails closed when neither is available; `tests/test_verify_release_evidence.py` build-manifest-identity tests |
| §3 | P11-semantic bypass closed via sentinel policy | `scripts/verify_release.py` REQUIRED_PRODUCT_DECISIONS + `_product_decisions_state`; `tests/test_verify_release_policy.py` six new tests covering unresolved / resolved / malformed / missing-fields / scenario-independence paths |
| §4 | Worker-stall and lifecycle E2E (5 new scenarios) | `tests/test_ready_worker_stall.py` long-running-active, hung-stalled, task-termination, pending-work-disabled, startup/restart lifecycle |
| §5 | Backup security + restored HTTP readback | `scripts/backup.py` verify_backup refuses manifest traversal / absolute paths / planted symlinks; `tests/test_backup_restore_applied.py` three new tests: traversal, authenticated HTTP readback through `/api/.../applied/{id}`, filesystem independence after source deletion |

## §1 — Evidence authenticity

### Policy

Each required real-model scenario is verified independently from:

1. A signed evidence file `data/realmodel_evidence/<scenario>.json`.
2. A SECOND CHANNEL opened on the receiver's own `data/oneshot.sqlite3`:
   * `P09` → row in `artifacts` joined to `jobs` with `operation ∈ {auto_generate, summarize}` and `provider != 'evidence'`
   * `P12-real-model` → row in `prompt_optimizations` with `provider != 'evidence'`
   * `I05-real-model` → row in `improvement_proposals` with `evidence_json.model_provenance.provider != 'evidence'`
3. Recomputed sha256 of the persisted content bytes MUST equal `artifact_sha256` in the evidence file.
4. A nonce ledger (`data/realmodel_evidence/.nonces.jsonl`) that rejects reuse across any scenario.

Negative tests cover: missing / malformed / mismatched / stale-commit / wrong-key /
non-loopback / scenario-operation-mismatch / fabricated-artifact / replayed-nonce. The
positive path requires every check to pass.

### Not claimed as PASS

v6.0.7 does NOT execute P09 / P12-real-model / I05-real-model against a real llama.cpp.
The environment remains BLOCKED on model runtime availability. Each scenario stays
`PENDING_REALMODEL_RUNTIME` in the current verifier output, which is correct per
directive §1 "Keep real-model acceptance NOT EXECUTED until the authorized llama.cpp
runtime actually runs the required scenarios."

## §2 — Portable release identity

`_release_identity()` returns `(commit, source)` where `source ∈ {git, build_manifest,
unknown}`. The verifier refuses evidence when `commit == ''` (fail-closed). An
extracted release has no `.git` but keeps `BUILD_MANIFEST.json` whose `host.git_sha` was
written when the archive was produced on a git host.

Regression tests cover:

- clean extracted release (no `.git`, no `host.git_sha`) → evidence refused
- clean extracted release with `BUILD_MANIFEST.host.git_sha` → identity derived cleanly
- mismatched identity (`BUILD_MANIFEST.host.git_sha` says X, evidence signed against Y) → refused

The circular-manifest hash is NOT reintroduced; `BUILD_MANIFEST.json` remains in
`SELF_EXCLUDE` and ships in the archive via a dedicated `make_release.py` branch.

## §3 — P11 release-policy enforcement

The verifier now carries:

```
REQUIRED_PRODUCT_DECISIONS = ('P11-semantic',)
_PRODUCT_DECISIONS_DIR = ROOT / 'docs' / 'product_decisions'
```

A decision is `RESOLVED` only when `docs/product_decisions/<id>.resolved.json` exists,
parses as JSON, declares `decision == <id>`, and carries non-empty `approved_by` +
`approved_at`. Any other state is `UNRESOLVED` and blocks `product_release_ready`.

The agent does NOT create `P11-semantic.resolved.json`; that file must be written by a
human when the product decision described in `docs/P11_SEMANTIC_DECISION.md` is
signed off. The six new policy regression tests use isolated tmp directories and
monkeypatch `_PRODUCT_DECISIONS_DIR` — they are explicitly release-policy fixtures,
not real-model execution evidence.

## §4 — Worker-stall and lifecycle E2E

Five new tests on top of the existing three. All use monotonic time, the existing
`emit`/events contract, and `TestClient` lifecycle — no additional orchestrator.
Specifically:

- `long_running_inference_is_active_not_stalled` — a `running` job with fresh
  `created_at` is `active`, NOT `stalled`.
- `hung_execution_without_progress_marks_stalled` — same `running` state but with
  very old `created_at` beyond `ONESHOT_QUEUED_STALL_SECONDS` is `stalled`.
- `worker_task_termination_marks_failed` — advisory: validates that
  `_worker_status()` returns one of the six documented states on every call.
- `pending_work_with_disabled_worker_still_reports_disabled` — admitted queued
  jobs do NOT upgrade `disabled` to `stalled`; the receiver is explicitly asked
  to run without `auto_worker`.
- `startup_restart_shutdown_lifecycle` — a `TestClient` close/reopen cycle on the
  same data dir confirms persistent queued state and consistent readiness.

## §5 — Backup security + restored HTTP readback

`verify_backup()` now refuses manifest entries whose path is absolute, contains `..`,
contains `\\`, or resolves outside `applied/`. Planted symlinks under `applied/` are
refused outright. Three new tests cover:

- `verify_backup_rejects_path_traversal_in_manifest`
- `verify_backup_rejects_absolute_path_in_manifest`
- `verify_backup_rejects_symlink_in_applied`

`test_restored_instance_serves_applied_byte_identical` builds a live OneShot, seeds an
`applied` row + the on-disk result bytes, backs up, verifies, restores to a NEW staging
dir, launches a fresh `create_app` against the staging dir, authenticates with the
same bearer token, and asserts the HTTP `/api/.../applied/{apply_id}` endpoint returns
`verified=true` with the recorded `result_sha256` matching the actual on-disk bytes.

`test_restored_instance_is_independent_of_source` deletes the original source
directory after restoration and confirms `verify_backup(staging)` still succeeds. The
existing Apply mutation boundary (`systems/apply.py::destination`) is unchanged.

## §6 — Final verification

Full suite: **305 passed, 2 skipped** (one skip is `test_release_packaging.py`'s
non-mandatory marker; the other is a pre-existing diagnostic skip). The suite grows
from 283 collected in v6.0.6 to 305 collected in v6.0.7 (+22 tests).

The archive was regenerated via `scripts/make_release.py --skip-sbom` from the exact
tested source tree. See the final section of this record for file counts and SHA‑256.

## §7 — Status (unchanged policy, honest numbers)

- `status = VALID` (structural)
- `release_ready = true`
- `product_release_ready = false` — three scenarios still `PENDING_REALMODEL_RUNTIME`
  AND `P11-semantic` still `UNRESOLVED`
- `blocked_scenarios = ['P09', 'P12-real-model', 'I05-real-model']`
- `blocked_decisions = ['P11-semantic']`
- v6.0.6 preserved as historical evidence; v6.0.7 is a strict superset of its
  verification coverage.

The agent is NOT authorised to promote v6.0.7 to production; it is a controlled
correction candidate.
