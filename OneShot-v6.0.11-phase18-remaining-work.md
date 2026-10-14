# v6.0.11 — Remaining-work ledger closure (2026-10-13T00:50Z)

Append-only follow-up to :file:`v6-phase17-deadcode-and-market-gap.md`.

Executed under the directive **"OneShot — Final Remaining-Work Implementation
and Acceptance Plan"** (B-01–B-03, C-01, D-01, M-01–M-03, O-01, S-02).

## Phase 0 — reconciled ledger (physical source read of v6.0.10)

Baseline: `oneshot-complete-release-2026-10-12-v6.0.10.tar.gz`
SHA‑256 `57ca9b4793436f48a9cdbe2891c8df5685ccddda60422952e4b653ac078bdb25`.

Classification per directive §2 vocabulary:

| ID | Observed physical state | Classification | Action this turn |
|---|---|---|---|
| **C-01** | `.github/workflows/ci.yml` invokes 6 of 9 runtime-independent E2E suites; `e2e_prompt_workspace`, `e2e_improvement_loop`, `e2e_improvement_loop_closure` are missing | **TEST GAP** | **FIX** |
| **D-01** | `README.md` has 0 references to `docs/E2E_MATRIX.md` | **TEST GAP (doc discoverability)** | **FIX** |
| M-01 | `pyproject.toml` has 0 metadata fields (no `license`, `classifiers`, `authors`, `readme`, `urls`) | OPTIONAL — project is private, no PyPI distribution consumer | **DEFER** per directive §8 M-01 column |
| M-02 | 79 FastAPI route handlers; 1 uses `response_model`; none use `summary=`/`tags=` | OPTIONAL — no accepted OpenAPI consumer | **REJECT** per directive §8 M-02 column |
| M-03 | `capabilities/researcher/tools/web_extraction.py:5` — `attrs` unused in HTMLParser callback | KEEP — directive §8 M-03 ("leave the documented false positive unchanged if suppression increases noise"). Vulture is not part of the project's accepted lint config; adding a vulture allowlist file for one false positive is net new noise. | **KEEP** |
| O-01 | No JSON log formatter | OPTIONAL — single-operator deployment with no log aggregator | **DEFER** per directive §8 O-01 column |
| **S-02** | **Already done** — `systems/api.py:182` already uses `f'ip:{ip}|sess:{session_cookie[:16]}'` as the rate-limit bucket key. The v6.0.10 proposal mislabelled this as pending. | KEEP (DONE) | Record as resolved; no change |
| B-01 | P09 / P12-real-model / I05-real-model: no reachable llama.cpp, no `ONESHOT_EVIDENCE_HMAC_KEY` in this sandbox | **BLOCKED** — directive §12 stop condition "External credentials or runtime unavailable" | Report; do not fabricate |
| B-02 | P11-semantic: no product-decision writer; `docs/product_decisions/P11-semantic.resolved.json` not present | **DECISION REQUIRED** — directive §12 "Genuine product decision" | Report; agent does not author this |
| B-03 | Vision E14: no `ONESHOT_VISION_*` env, no vision-capable GGUF | **BLOCKED** — operator-owned environment | Report |

### S-02 physical evidence

```
systems/api.py:182:        bucket_key = f'ip:{ip}|sess:{session_cookie[:16]}'
systems/api.py:183:        if not _rate_allow(bucket_key):
```

The bucket key combines client IP and the first 16 chars of the session cookie — the exact remediation the v6.0.10 proposal recommended. Verified independently. No change required.

## Pass B — controlled implementation

Only the two **REQUIRED** items from Phase 0 landed:

### C-01 — CI full E2E coverage

`.github/workflows/ci.yml` additions:

- Appended three steps to the `e2e:` job:
  - `uv run python -m tests.e2e_prompt_workspace`
  - `uv run python -m tests.e2e_improvement_loop`
  - `uv run python -m tests.e2e_improvement_loop_closure`
- Renamed job display name: `e2e (http + presend + browser)` → `e2e (http + presend + browser + prompts + improvement loop)`.
- Added `timeout-minutes: 30` to bound stuck Playwright runs (directive §4 "Set bounded timeouts appropriate to observed execution"; this is well above the ~15–20 minute observed worst case).

Regression test added: `tests/test_ci_e2e_contract.py` — three assertions:

1. CI invokes every `tests.e2e_*` suite in the `REQUIRED_E2E_SUITES` tuple.
2. The `e2e:` job declares `timeout-minutes`.
3. CI does NOT invoke `tests.e2e_live_model` or `tests.e2e_vision_local` (those are gated by the real-model acceptance contract, not deterministic CI).

### D-01 — README cross-reference

`README.md` "Integrated diagnostics" paragraph now ends with:

> See \`docs/E2E_MATRIX.md\` for the full E2E matrix mapping every supported System workflow to its executable suite, prerequisite environment, and current outcome.

Regression test added: `tests/test_docs_cross_references.py` — three assertions:

1. README references `` `docs/E2E_MATRIX.md` ``.
2. `docs/E2E_MATRIX.md` actually exists on disk.
3. The four pre-existing README → docs links also still exist (`MODEL_INTEGRATIONS`, `PRE_SEND_CONTEXT_REVIEW`, `SYSTEM_BACKGROUND`, `INSTALL_RELEASE_GATES`).

## Pass B — regression evidence

Full pytest from the modified source (frontend built, env freshly synced):

```
313 passed, 2 skipped, 2 failed in 44.31s
```

The two failures are expected manifest-staleness in `test_release_packaging.py` after source modification; they clear after `scripts/make_release.py` regenerates `BUILD_MANIFEST.json`. Verified by re-running pytest from the extracted packaged tarball.

Prior v6.0.10 regression baseline: **309 passed, 2 skipped**. Delta: **+6** (3 C-01 contract tests + 3 D-01 doc-link tests).

## Not executed this turn (BLOCKED by directive §12)

- **B-01** real-model execution — no local llama.cpp runtime, no `ONESHOT_EVIDENCE_HMAC_KEY`. Agent cannot forge inference evidence; verifier correctly refuses signed-but-unverified evidence via the Phase-14 second-channel + Phase-15 release-identity contracts.
- **B-02** P11-semantic — directive §12 is explicit that this is a product-decision stop condition. The agent does not author `docs/product_decisions/P11-semantic.resolved.json`; the four questions in `docs/P11_SEMANTIC_DECISION.md` remain the product owner's work.
- **B-03** vision E14 — no `ONESHOT_VISION_*` env, no vision-capable GGUF accessible from the sandbox.

Per directive §11 and §12: product release readiness remains **BLOCKED** on B-01 + B-02 (B-03 is optional per the shipped product classification).

## Final status

- Structural verification: **VALID**
- System E2E verification: **PASS** (313 pytest; 9 independent E2E suites all pass from the packaged tarball — see `e2e_transcript_v6.0.11.txt`)
- CI coverage: **COMPLETE** (every runtime-independent E2E suite now in CI with a pinning regression test)
- Real-model verification: **NOT EXECUTED** (B-01 blocked)
- Semantic verification: **UNRESOLVED** (B-02 blocked)
- Vision verification: **PREREQUISITE_MISSING** (B-03 blocked)
- `product_release_ready = false` — unchanged
- Promotion to production: **not authorised**
- v6.0.6 → v6.0.10 preserved as historical evidence

Per directive §10: v6.0.11 is issued because two source corrections landed (C-01 CI pin + D-01 README link) with two new regression tests. v6.0.10 is retained intact.
