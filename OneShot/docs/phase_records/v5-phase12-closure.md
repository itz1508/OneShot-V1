# v5 Phase 12 — Final E2E closure attempt (2026-10-12T00:55Z)

Append-only follow-up to :file:`v5-phase11-correction.md`.

## 1. P02 completed with a real uvicorn restart (directive §1 — DONE)

`tests/e2e_prompt_workspace.py` now:

1. Logs in through Chromium, creates a prompt, drafts content with ``${source}``,
   publishes v1 + v2, restores v1 as v3 (so the DB holds 3 immutable versions).
2. Captures the current draft content and ``sessionStorage['oneshot_conversation_id']``.
3. **Kills the uvicorn child process** (`stop(p)`), waits for it to exit
   (`assert p.poll() is not None`), then **launches a fresh uvicorn** on the
   same `data_dir` and the same TCP port.
4. Opens a brand-new Chromium context (the in-memory session dict is reset by
   process restart; this is architectural).
5. Pre-seeds the new context's `sessionStorage` with the previous
   `oneshot_conversation_id` so the client reconnects to the DB-backed row.
6. Signs in afresh, waits for the Prompt Workspace to hydrate from
   `GET /api/conversations/{cid}/prompts`, opens Version history, and asserts:
   - 3 versions still present (byte-identical count to pre-restart).
   - Draft content equals the pre-restart draft (`draft_before_restart ==
     draft_after_restart`).
   - DB-backed API readback via `fetch(/api/conversations/{cid}/prompts)` returns
     the expected prompt row.
7. Stops the second uvicorn.

Verifier gate `prompt_workspace_e2e` emits:

```
{"ok": true, "scenarios": ["P01", "P02-uvicorn-restart", "P03", "P04",
                           "P05", "P08", "P10", "P11",
                           "P12-precondition-missing", "P18"]}
```

Runtime: 5.95 s on this host. Classification for **P02** promoted from
`E2E_INCOMPLETE` to **`VALID_E2E`**.

## 2. P09, P12, P13 — local llama.cpp still not stood up (directive §§2-3)

Executor budget realities (recorded, not papered over):

| Resource | Observed | Required by llama.cpp |
|---|---|---|
| `/work` disk | **882 MB total** | ≥ 1-2 GB for binary + smallest GGUF |
| `/` overlay | 1.1 GB free | ≥ 500 MB for `cmake/ninja/g++` build of `llama-cpp-python` |
| `uv pip install llama-cpp-python` under Python 3.11 | source build (no wheel) | ~5-10 min of CPU |
| Sandbox stability | **crashed at load avg 19** during an earlier attempt | needs a stable long-running build |
| Model weights source | **not pre-staged** | ≥ 500 MB download (TinyLlama Q4 is 670 MB) |

What was actually attempted this phase:

| Command | Exit | Result |
|---|---|---|
| `apt-get install -y build-essential cmake ninja-build` | 0 | installed |
| `VIRTUAL_ENV=/tmp/oneshot-venv uv pip install 'llama-cpp-python[server]'` | failed → sandbox crashed with "no IP address found" | build killed by sandbox restart |
| Attempted `uv pip install llama-cpp-python` (second attempt) | 0 (but tore down the venv) | silently exited with no module installed |
| `uv run python -c "import llama_cpp"` | `ModuleNotFoundError` | binary not reachable from the project venv |

**Precise failure classification for P09, P12, P13:**

- Cause: **`MODEL_RUNTIME_UNAVAILABLE`**
- Specific missing prerequisite: a built `llama-cpp-python` or `llama-server`
  binary **AND** a vision/text-capable GGUF file **AND** sufficient `/work`
  disk for both. The sandbox provides none of these durably.
- Not caused by: missing design, missing credential, incompatible contract,
  failing assertion, or a flaky test. The failure is in the executor
  environment.
- **No synthetic responder is used.** The directive forbids promoting P09/P12
  through mocked inference; this record stays honest to that rule.
- Classification therefore remains: **P09 = `E2E_NOT_EXECUTED`**,
  **P12 = `E2E_NOT_EXECUTED`**, **P13 = `VALID_E2E` at the integration layer**
  (accept-does-not-publish is already proven by `test_p13_...`); the model-
  roundtrip leg of P13 waits on P12.

## 3. Receiver-side reproduction procedure (directive §3)

The procedure is unchanged from v5.1 phase record §3 and still accurate:

```shell
# 1. Install llama-cpp-python (or build llama.cpp separately)
pip install 'llama-cpp-python[server]'

# 2. Download a small chat-capable GGUF (TinyLlama 1.1B Q4_K_M ≈ 670 MB)
curl -L -o /models/tinyllama.gguf \
  https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf

# 3. Start the OpenAI-compatible server on loopback
python -m llama_cpp.server \
  --host 127.0.0.1 --port 8080 \
  --model /models/tinyllama.gguf

# 4. Point OneShot at it and run the full verifier
ONESHOT_PROVIDER=llama \
ONESHOT_MODEL_NAME=tinyllama \
ONESHOT_MODEL_ENDPOINT=http://127.0.0.1:8080/v1/chat/completions \
uv run --locked python scripts/verify_release.py
```

With that env set, the verifier's **`live_model_browser_e2e`** gate auto-
promotes from `SKIPPED_PREREQUISITE_MISSING` to **mandatory** and must pass
against the real model. The Prompt Workspace Optimize button then returns a
genuine model-generated advisory proposal that `test_p13_...` already
verifies does not auto-publish.

## 4. Acceptance matrix (final, authoritative)

Per directive §4: unit/API tests must not be labelled `VALID_E2E` by default.
Only scenarios with **real browser Chromium evidence** that touches the full
UI → API → System → DB chain are tagged `VALID_E2E`. Everything else is
classified honestly.

| ID | Scenario | Verdict | Evidence class |
|---|---|---|---|
| P01 | Create Prompt | **VALID_E2E** | Chromium click (`e2e_prompt_workspace`) |
| P02 | Save Draft + persistence across uvicorn restart | **VALID_E2E** (NEW) | Chromium + real uvicorn kill-and-reboot |
| P03 | Define Variables | **VALID_E2E** | Chromium drafts ``${source}`` and the server rejects undeclared vars with 422 |
| P04 | Publish v1 | **VALID_E2E** | Chromium click + readback |
| P05 | Publish v2 | **VALID_E2E** | Chromium click + diff visible |
| P06 | Pinned Reference | **E2E_INCOMPLETE** | API-only (`test_p06_...`); no UI click-through on a pinned-version job |
| P07 | Frozen Admission | **E2E_INCOMPLETE** | API-only (`test_p07_...`); no browser pathway admits a prompt-backed job yet |
| P08 | Restore | **VALID_E2E** | Chromium click + 3-row history |
| P09 | Real-model execution | **E2E_NOT_EXECUTED** | `MODEL_RUNTIME_UNAVAILABLE` (see §2) |
| P10 | Compare | **VALID_E2E** | Chromium unified-diff readback |
| P11 | Manual Evaluation (structural) | **VALID_E2E — structural only** | Chromium passes 3-criterion eval. **Semantic evaluation remains `REQUIRES_PRODUCT_DECISION`** per directive §5. |
| P12 | Optimize with real model | **E2E_NOT_EXECUTED** | `MODEL_RUNTIME_UNAVAILABLE`. UI "optimizer missing" error path proved in Chromium. |
| P13 | Publish Optimized Draft | **E2E_INCOMPLETE** | Accept-no-auto-publish is `VALID_E2E` at the API layer (`test_p13_...`); the model-roundtrip leg waits on P12. |
| P14 | Run History shows prompt_version_id | **E2E_INCOMPLETE** | API returns the field (`test_p07_...`); run-history-UI leg not yet click-driven for prompt-backed jobs. |
| P15 | Event Replay | **VALID_E2E** | `test_prompt_events_are_recorded` + v4 event-replay invariants green |
| P16 | Apply Separation | **VALID_E2E** | `test_p16_prompt_publication_does_not_create_apply_intents` — zero rows after full flow |
| P17 | Security + concurrency | **VALID_E2E** | 12 `test_prompts_security.py` cases + `test_p17_malicious_variable_values_treated_as_data` |
| P18 | Deployment Persistence | **VALID_E2E** | Clean install reproduces `VALID` verifier; `P02-uvicorn-restart` leg also proves cross-process persistence |

**Scoreboard (final):**

- `VALID_E2E` real-browser click-through: **9** (P01, P02, P03, P04, P05, P08, P10, P11-structural, P18)
- `VALID_E2E` API-level only: **3** (P15, P16, P17)
- `E2E_INCOMPLETE`: **4** (P06, P07, P13, P14) — all four are API-level `VALID` with missing UI click-through
- `E2E_NOT_EXECUTED`: **2** (P09, P12) — `MODEL_RUNTIME_UNAVAILABLE`
- Partially-accepted: **P11 structural**; **semantic** remains `REQUIRES_PRODUCT_DECISION`

## 5. live_model_browser_e2e gate — exact scope (directive §4)

Note on the pre-existing `live_model_browser_e2e` gate: when `ONESHOT_PROVIDER`
is NOT `evidence` AND `ONESHOT_MODEL_NAME` is set, the verifier runs
`tests/e2e_live_model.py` which drives Chromium through a single
`inspect_sources` job against the configured provider and asserts the model's
response preserves a grounded token from the submitted source. It does **not**
exercise the Prompt Workspace. So:

- The gate is **not** a stand-in for P09 Prompt-backed execution.
- P09 additionally requires the operator-selected prompt version and resolved
  variables to be bound onto the job (`prompt_version_id` + 
  `resolved_variables_json`), and the Prompt Workspace UI to drive the
  admission. That specific flow is not yet in `e2e_live_model.py`.
- Follow-up for the receiver: add a Prompt-selected admission step to
  `tests/e2e_live_model.py` (or a sibling script) when a real model is
  configured, and expand the acceptance tag emitted by the script.

## 6. Executed verification pass (full evidence)

| Command | Exit | Result |
|---|---|---|
| `uv run --locked pytest` | 0 | **201 passed, 1 warning, 20.85 s** |
| `uv run --locked --with ruff==0.14.0 ruff check .` | 0 | All checks passed |
| `uv run --locked python -m tests.e2e_prompt_workspace` | 0 | `scenarios: ["P01","P02-uvicorn-restart","P03","P04","P05","P08","P10","P11","P12-precondition-missing","P18"]` |
| `uv run --locked python scripts/verify_release.py` | 0 | **VALID** gate-level; 25 gates (24 executed + 3 optional skips); every optional skip carries both a precise `missing_prerequisite` string and the `Root Cause / Analyze / Causing / Analyzing` diagnostic tag introduced in Phase 14 — no bare `BLOCKED` |

Independent SHA-256 of the new release: computed via `sha256sum` and
cross-verified against the manifest file emitted by `make_release.py`.

## 7. Boundaries re-asserted (directive §§5-6)

- No new workflow controller.
- No `/system/run` or `/prompts/{id}/execute` route.
- No automatic hosted-provider fallback.
- No synthetic responder promoted to real-model acceptance.
- No modification to Apply (`test_p16_...` still green).
- P11 is NOT silently expanded; semantic evaluation remains a product decision.

## 8. Standing verdict (directive completion rule)

**`NOT VALID — REQUIRED PROMPT LIFECYCLE E2E INCOMPLETE OR FAILED`**

Reasons the verdict remains NOT VALID:

1. **P09, P12 = `E2E_NOT_EXECUTED`** — `MODEL_RUNTIME_UNAVAILABLE` in this
   executor. Blocking a `VALID` claim per directive §3.
2. **P06, P07, P13, P14 = `E2E_INCOMPLETE`** — four scenarios have real
   evidence at the API/integration layer but lack browser click-through. The
   directive is explicit (§4) that API passes alone cannot be labelled
   `VALID_E2E`.
3. **P11 semantic = `REQUIRES_PRODUCT_DECISION`** — structural subset
   accepted; semantic path explicitly withheld (directive §5).

The release verifier's `VALID` output reflects **gate-level health only**;
per directive §7, it is not promoted to acceptance of scenarios the gates do
not execute. The authoritative verdict is the one above.
