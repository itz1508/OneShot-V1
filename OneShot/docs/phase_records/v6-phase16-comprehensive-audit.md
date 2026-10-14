# v6.0.9 — Comprehensive audit of v6.0.8 (2026-10-12T21:00Z)

Append-only follow-up to :file:`v6-phase15-full-e2e-verification.md`.

Executed under **"OneShot — Comprehensive System Audit, Logical Correction,
Hardening and Simplification"**. Directive summary:

- Inspect the whole system; identify terminology / logic / overbuilt /
  underbuilt / security defects.
- **Do not redesign.** Preserve accepted behavior.
- `KEEP` / `NO CHANGE REQUIRED` is a valid audit outcome; do not force every
  low-value observation into a code change.
- Issue a new release only when source changes are justified.

## Pass A — read-only findings

Methodology:

- Full physical scan of 164 source files from the v6.0.8 tarball
  (SHA‑256 `84465f3e…56fb`).
- `ruff==0.14.0 check` — **All checks passed!** (0 F401 unused imports; selected rule set F,B,UP,SIM).
- `vulture==2.14 --min-confidence 80` — 2 findings:
  - `scripts/backup.py:98` — `rel_parts=pathlib.Path(rel_name).parts if False else rel_name.split('/')` — **dead ternary** (unsatisfiable condition).
  - `capabilities/researcher/tools/web_extraction.py:5` — `attrs` unused — **false positive**: stdlib HTMLParser callback signature.
- `grep -rn "TODO\|FIXME\|XXX\|DEPRECATED" systems scripts capabilities frontend` → **0 matches**.
- `grep -rE "agent-first|multi-agent|AgentController|AgentManager"` → **0 matches**.
- Full pytest with `frontend/dist/` built → **305 passed, 2 skipped, 0 failed** in 37.03 s.
- Terminology audit (shipped in v6.0.8 as `OneShot-v6.0.8-terminology_ledger.md`) → **0 renames required**.

### Classified findings

| ID | Category | Severity | Action |
|---|---|---|---|
| **L01** | Dead-code expression `if False` in `scripts/backup.py:98` | COSMETIC | **FIX** (one-line) |
| L02 | `attrs` unused in `web_extraction.py` HTMLParser callback | IGNORE (false positive) | KEEP |
| D01 | Phase-13 record says "162 members / 163 lines" but v6.0.6 shipped 160 manifest entries → 163 archive members → 164 SHA256SUMS lines | HISTORICAL | KEEP (append-only) |
| T01 | 6 ready-tests fail with confusing message when `frontend/dist/` is absent | DOCUMENTATION | KEEP (prerequisite documented in `docs/E2E_MATRIX.md`) |
| R01 | `scripts/winml_feasibility.py` only used by its own tests | INTENTIONAL | KEEP (operator probe) |

### Overbuilt / underbuilt watchlist

| Candidate for consolidation | Verdict |
|---|---|
| `scripts/verify_release.py::_git_sha` vs `_release_identity` | **KEEP both** — different authority levels (diagnostic vs fail-closed replay check) |
| `tests/test_backup_restore_applied.py` vs `tests/test_restore_staging.py` vs `tests/e2e_backup_restore.py` | **KEEP all** — non-overlapping assertions |
| `scripts/smoke_http.py` vs `tests/e2e_http.py` | **KEEP both** — operator diagnostic vs full worker lifecycle E2E |
| `systems/background.py` + `systems/improvement_loop.py` | **KEEP both** — background is advisory read-only; improvement_loop owns writes |

Underbuilt items **DEFERRED** by directive scope:

- P09 / P12-real-model / I05-real-model → external prerequisite (llama.cpp + HMAC key) per directive §11.
- P11-semantic → product decision, directive §11.
- MFA, distroless, OTel exporters, signing infrastructure → REJECTED by directive §8 ("Do not automatically add...").
- New worker orchestrator → REJECTED by directive §13.

## Pass B — controlled implementation

### Single applied correction

**L01 — `scripts/backup.py:98`:**

Before:

```python
rel_parts=pathlib.Path(rel_name).parts if False else rel_name.split('/')
```

After:

```python
rel_parts=rel_name.split('/')
```

Behavior is unchanged — the `if False` branch was unreachable; the `else`
branch is what always executed. Regression confirmed by
`tests/test_backup_restore_applied.py::test_verify_backup_rejects_path_traversal_in_manifest`
and companion traversal/absolute/symlink tests (**10/10 pass**).

### Everything else intentionally retained

- Zero schema / API / event / UI changes.
- Zero file additions beyond this phase record.
- Zero file deletions.
- Zero dependency changes.
- Zero new tests (existing coverage already proves the corrected behavior).

## Final verification

- `ruff check .` — **All checks passed!**
- `vulture --min-confidence 80 systems/ capabilities/ scripts/` → L01 cleared; only the `web_extraction.py` HTMLParser-signature false positive remains.
- `uv run python -m pytest --tb=no` — **305 passed, 2 skipped, 0 failed** in 37-38 s.
- `uv run python -m pytest tests/test_backup_restore_applied.py` — **10/10 pass** in 0.44 s.

## Status

- v6.0.6, v6.0.7, v6.0.8 preserved as historical evidence.
- v6.0.9 ships with one three-line change (`scripts/backup.py`) plus this append-only phase record.
- `product_release_ready = false` unchanged (P09/P12/I05 blocked on real-model runtime; P11-semantic blocked on product decision).
- Promotion to production **not authorised**.

Per directive §16 G ("Do not issue a new version merely because an audit found
nothing that requires implementation"): a new release IS issued here because
one source change was applied, however small. The release package is called
`v6.0.9`; v6.0.8 is preserved intact.
