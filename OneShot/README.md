# OneShot System — fresh candidate rebuild

**Build gate:** NOT VERIFIED until clean Python 3.11 dependency resolution, Docker build/restart, and real Chromium frontend-to-backend E2E all complete. The build source is an executable candidate, not a verified deployment.

## Scope actually implemented

- Primary **System Chat**, source attachments, source selection, text reader, Advisor checklist, and System Auto Generator evidence packet; real persisted Worker/Run/event trace, original integrity, separate revisioned drafts, explicit Apply/readback.
- Same-origin, operator-password **browser session**: HttpOnly SameSite cookie, server-held CSRF nonce, login rate limit, sign out. API bearer token remains server-side for CLI use. Both credentials are configured through server environment variables. Local bind only by default.
- Browser UI: Login, System Chat, source review/draft, source processing, Process Display from actual events, evidence result. Browser assets built by Node 22 and served by FastAPI.
- Agent Chat is **optional**, with server-configured OpenAI, Gemini or local Ollama connections and a real authenticated reply route. No agent provider is active without explicit server configuration. The Agent never owns System workflow authority.
- **Unsupported, not simulated:** image/PDF semantic understanding, real internet research retrieval, semantic correctness without a live model and labeled evaluation set, automatic Agent installation. Server-side multi-provider transport is implemented, but third-party credentials, installed model availability and model quality must be verified separately.


## Integrated multi-provider transport (not live-model verified)

System generation is selected server-side through `ONESHOT_PROVIDER=evidence|model|openai|gemini|ollama`, with an explicit model ID, endpoint/credentials where applicable. OpenAI-compatible mode, native Gemini `generateContent`, and local Ollama `/api/chat` have distinct bounded request/response adapters in `systems/model_transport.py`. Models are never granted source mutation, tools, source management, or Apply authority. The System verifies `GeneratedDocument` and source-ID coverage after generation. Default evidence mode remains available with no model credentials.

Agent Chat is an optional separate interface. Explicit `ONESHOT_AGENT_OPENAI_*`, `ONESHOT_AGENT_GEMINI_*`, or `ONESHOT_AGENT_OLLAMA_*` environment configuration makes those entries visible in the Agent dropdown, with an authenticated reply route. Agent and System access are mutually exclusive for writes; the Agent can reply to Agent Chat, not call System tools. The System stays usable with no Agent configured. See `docs/MODEL_INTEGRATIONS.md` for the exact settings, limitations and gate requirements.

**Integrated diagnostics:** `python -m tests.e2e_http` exercises real Uvicorn/evidence processing. `python -m tests.e2e_multi_provider_http` exercises real Uvicorn plus a local Ollama-compatible HTTP protocol responder, Agent session/reply, System job/persistence, real events, Apply readback and restart. The responder is **not a real model** and those results do not establish semantic quality. Browser E2E and live-provider external requests remain unverified. See `docs/E2E_MATRIX.md` for the full E2E matrix mapping every supported System workflow to its executable suite, prerequisite environment, and current outcome.

## System Background (implemented candidate)

This candidate includes `systems/background.py` and a non-Agent System-owned
background evaluator. It observes committed terminal foreground jobs, checks
source integrity and trace/artifact provenance, records actual evaluation
states, and reports repeated deterministic issue patterns as advisory
suggestions. It never generates correctness labels, trains from job completion,
or promotes production policies automatically.

The background evaluator has a dedicated single-thread executor and **yields to
all queued/running foreground jobs**. SQLite schema version 3 supplies durable
admission, stable evaluator IDs, atomic claim, retry bounds, and restart
recovery for the existing single-server deployment. Set
`ONESHOT_SYSTEM_BACKGROUND=false` to disable automatic evaluation.

The browser has a separate System Background display with existing SSE event
notifications and a read-only polling fallback. No Agent integration is used.

See [docs/SYSTEM_BACKGROUND.md](docs/SYSTEM_BACKGROUND.md) for detailed
contract, limitations, commands, and mandatory production verification gates.

**Verification caveat:** The isolated candidate's Python 3.13 and live HTTP
checks do not establish the target Python 3.11 lock build, Docker deployment,
or complete authenticated Chromium E2E.

**Installation and release prerequisite:** Read [docs/INSTALL_RELEASE_GATES.md](docs/INSTALL_RELEASE_GATES.md) before installation. It includes **uv installation** on Windows/Linux/macOS, Python 3.11 installation and verification, clean npm/Playwright setup, provider settings, and mandatory release gates. This candidate **does not include `uv.lock`**, and the updated Dockerfile now requires the missing reviewed lock before it can build. Therefore the existing short commands below are an **initial resolution sketch**, not a reproducible or production-verified install. Do not release until an approved Python 3.11 lock and lock-equivalent Docker installation are verified.

## Clean install (target: Python 3.11, Node 22+)

Python dependencies are declared once in `pyproject.toml`; `uv.lock` must be generated against the target interpreter and registry (it is not fabricated in this package):

```bash
uv python install 3.11
# .python-version already pins 3.11; no additional pin command required
uv lock --python 3.11    # first resolution only; inspect and commit uv.lock
uv sync --locked --extra test --python 3.11
cd frontend
npm ci
npm run build
cd ..
```

`frontend/package-lock.json` is a real zero-dependency lock generated by npm 10 in offline mode. No JS framework or external npm package was introduced without a consumer. A successful `npm run build` produces the static `frontend/dist/` tree. This does not establish an E2E verdict.

## Run locally

Set the following on the *server*, not in browser JavaScript or committed configuration:

```bash
export ONESHOT_API_TOKEN='replace-with-a-long-random-secret'
export ONESHOT_BROWSER_PASSWORD='replace-with-a-different-secret-password'
export ONESHOT_DATA_DIR='./data'
export ONESHOT_PROVIDER='evidence'
uv run python -m uvicorn systems.api:create_app --factory --host 127.0.0.1 --port 8787 --workers 1
```

Open `http://127.0.0.1:8787/` and sign in with the **operator password**, not a provider API key. Do not bind this single-operator runtime directly to the public internet. The browser session expires after 8 hours and must be reauthenticated after server restart; persisted source/job/message records survive.

Docker Compose is specified for one local host with persistent volume, loopback port binding, and one worker:

```bash
docker compose config
docker compose up --build -d --wait
```

Compose still requires **actual Docker execution** and clean Python 3.11 install before any deployment claim is valid. The Dockerfile now consumes a reviewed `uv.lock` and refuses to build when that lock is absent. Actual Docker installation and parity are not verified until the approved lock exists and the image runs.

## Required full-build/E2E gate

```bash
# Diagnostic only, never a completion verdict:
uv run python -m pytest -q
cd frontend && npm test && npm run check && npm run build && cd ..

# Real HTTP integration diagnostic, not browser E2E:
uv run python -m tests.e2e_http

# Real browser E2E; install Chromium if needed:
uv run python -m playwright install chromium
uv run python -m tests.e2e_browser
uv run python -m tests.e2e_presend
# With a real provider configured and approved:
uv run python -m tests.e2e_live_model
```

The required final verdict is **VALID only after the complete clean build, actual browser E2E, runtime security/failure behavior, and restart persistence all succeed**. A mock, unit test, API smoke, or HTTP integration diagnostic does not independently qualify.

## Explicit removed legacy artifacts

The isolated rebuild does **not** include the previously unauthorized `scripts/workflows/{deployment.py,pydantic_v2.py,market_gap.py}` or generated schema/doc claims with no runtime consumer. They were not needed to run the application. No existing ChatGPT Library files were deleted in preparing this candidate.

## System objective binding (workspace context)

Jobs now require `prompt_message_id` from a persisted System message in the same conversation; the stored job link survives restart. The existing Scanner and Advisor prepare selected immutable sources. Evidence mode emits an explicitly labeled **evidence packet**, including the objective, source hashes, versions, and numbered lines; it does not pretend to answer semantically. Opt-in model mode receives the objective separately from evidence data, without granting tool or Apply authority. The browser shows the latest sent System message as the processing objective before Start. Existing databases upgrade transactionally through schema version 5 without deleting jobs; queued legacy jobs with no objective fail closed when executed.

## Source names and stored bytes

`systems.file_store.FileStore` is content-addressed. Its physical files are SHA-256 digests, not user filenames. `systems.store.Store` owns the SQLite `sources` records with each source's `id`, original `name`, `sha256` and `version`; two distinct named sources may safely reference identical bytes. The System evidence packet preserves original names, source IDs, hashes, versions, and line-numbered text. Never infer a source's original name from a FileStore disk path. Backup and restore must verify every referenced source digest is actually present and unchanged.

The optional scikit-learn library was reviewed but not installed: there is no approved classifier or ranking consumer, and the existing selected scope is at most 2 MB. No extra NumPy/SciPy dependency tree was added.

## Optional System Chat pre-send review

The existing vanilla-JavaScript System Chat offers an opt-in review modal before saving a message. It copies explicitly labeled sections into an editable draft, displays the original verbatim and the exact outbound text, and requires approval. Cancel sends nothing. No semantic model or Agent is invoked, and saving a message does not automatically start processing. See `docs/PRE_SEND_CONTEXT_REVIEW.md` for behavior, tests and limits.

## Fail-closed full release check

After installing Python 3.11 and generating/reviewing `uv.lock`, run
`uv run --python 3.11 --locked python scripts/verify_release.py`.
This checks the declared interpreter, lock, frontend/backend, real HTTP and
browser suites and Docker image build. It exits nonzero and writes
`data/verification/last_run.json` when required gates are blocked or fail.
The script cannot independently certify real-model semantic quality and never
reports the complete product VALID on diagnostic tests alone.

The Dockerfile now **requires** `uv.lock` and uses `uv sync --frozen` on
Python 3.11, rather than resolving unpinned Python dependencies with pip.
No lockfile is fabricated in this environment. If `uv.lock` is missing,
Docker correctly refuses to build until it has been resolved and reviewed.

## Explicit supported System operations (current source)

The browser admits `inspect_sources` for read-only source inspection without a model,
`auto_generate` for evidence or configured model output, and `summarize` for a
**configured real model** to generate the strict one-key summary output.
`GET /api/conversations/{cid}/artifacts/{aid}/summary` exports the exact
`output.json` response *only* for a persisted model summary.
`REFERENCE_SOURCE` records a URL without fetching; an unfetched reference
is not silently converted into accessible source content.
Source removal and reattachment preserve the immutable original; user-visible
Apply writes managed output only after explicit confirmation and readback.

The live-browser model test in `tests/e2e_live_model.py` uses the actual configured
model, checks a labeled source fact, and downloads `output.json`; it **cannot** be
replaced with `tests.e2e_multi_provider_http` (local protocol responder).
The complete product remains NOT VALID while full UI / model / Python 3.11 /
Docker release gates remain unexecuted.


## Operator recipe — install, verify, backup, restore

Target environment: single-operator Linux/macOS host with Python 3.11, Node 22+, uv, Make, and (optionally) Docker.

### 1. Install

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv python install 3.11
uv sync --locked --extra test --python 3.11
cd frontend && npm ci && npm run build && cd ..
uv run playwright install chromium --with-deps
```

### 2. Run

```bash
export ONESHOT_API_TOKEN=$(openssl rand -hex 24)
export ONESHOT_BROWSER_PASSWORD=$(openssl rand -hex 16)
export ONESHOT_DATA_DIR=./data
uv run uvicorn systems.api:create_app --factory --host 127.0.0.1 --port 8787
# in another shell:
curl -fs http://127.0.0.1:8787/ready | jq .
```

### 3. Verify (full gate, evidence-derived VALID / NOT_VALID)

```bash
uv run python scripts/verify_release.py
cat data/verification/last_run.json | jq '.status, .mandatory_failed_gates'
```

Includes mandatory gates `ruff_lint`, `python_diagnostics`, `workflow_conformance`, `dockerfile_contract`, `frontend_check/tests/build`, `http_integration`, `multi_provider_protocol`, `browser_integrated_e2e`, `browser_presend_e2e`, `live_model_local_e2e`, `backup_restore_e2e`. Docker (`docker_compose_config`) and remote-provider live-model E2E (`live_model_browser_e2e`) stay optional with precise `SKIPPED_PREREQUISITE_MISSING` reasons when prerequisites are not on the host.

### 4. Backup

```bash
# scripts.backup backup <SOURCE_DATA_DIR> <NEW_BACKUP_DIR>
uv run python -m scripts.backup backup "$ONESHOT_DATA_DIR" ./snapshots/$(date +%Y%m%d-%H%M%S)
# For completeness, copy the applied/ directory alongside the backup:
cp -r "$ONESHOT_DATA_DIR/applied" ./snapshots/<timestamp>/applied
```

### 5. Restore

```bash
# scripts.backup restore <BACKUP_DIR> <NEW_STAGING_DIR>
uv run python -m scripts.backup restore ./snapshots/<timestamp> ./restored-staging
# Promote staging to the authoritative data dir
rm -rf "$ONESHOT_DATA_DIR"
cp -r ./restored-staging "$ONESHOT_DATA_DIR"
cp -r ./snapshots/<timestamp>/applied "$ONESHOT_DATA_DIR/applied"
# Full round-trip E2E (as the test runs):
uv run python -m tests.e2e_backup_restore
```

### 6. Docker

```bash
docker compose config          # static validation (always safe)
# Optional live smoke (requires a running docker daemon):
uv run python -m scripts.docker_smoke
```

### 7. Make a release artifact

```bash
uv run python -m scripts.make_release
#   writes dist/oneshot-release.tar.gz
#   writes dist/sbom.python.cyclonedx.json
#   writes dist/sbom.frontend.cyclonedx.json
#   embeds both SBOMs INSIDE the tarball under OneShot/dist/
#   writes dist/oneshot-release-SHA256SUMS.txt
```
