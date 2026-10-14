# OneShot — Clean Install, Dependencies and Production Release Gates

**Status: operational instructions; NOT proof of production readiness.** Target: desktop/web, single-operator OneShot. Mobile excluded. Follow the **active checked-out repository** after reconciling it with this archived candidate. Do not overwrite live source or a database by unpacking a ZIP into it.

## Required dependencies and exact owners

| Dependency | Required for | Declared / provenance | Status in audited ZIP |
| --- | --- | --- | --- |
| `uv` | Python interpreter, Python environment, lock and sync | Official Astral installer or package manager | This environment has uv 0.10.0; the target machine must install its own |
| Python 3.11 | System backend, data migration, tests | `.python-version`, `pyproject.toml` requires `>=3.11,<3.12` | NOT EXECUTABLE HERE: interpreter unavailable; download DNS failed |
| FastAPI, Uvicorn, Pydantic v2, HTTPX | App runtime | `pyproject.toml`, with broad semver ranges | Python 3.11-compatible versions must be resolved and locked |
| setuptools | Project wheel/build metadata | `[build-system]` in `pyproject.toml` | Lock/installation must establish effective version |
| pytest, Playwright Python | Diagnostic and real browser E2E | `pyproject.toml` optional `test` dependencies | Tests work on local Python 3.13; not verified on target 3.11 |
| Playwright Chromium browser | Real browser E2E | Installed separately with Playwright CLI | Browser launch possible here; local HTTP navigation blocked |
| Node.js 22+ and npm | Existing frontend build | `frontend/package.json`, `frontend/package-lock.json` | Node 22.16.0/npm 10.9.2 present in audit runtime |
| Docker Engine + Compose v2 | Container build, volume/restart validation | `Dockerfile`, `compose.yaml` | Not available in audit runtime |
| Real configured model and legally usable credentials | Required only for claimed live semantic/provider E2E | `docs/MODEL_INTEGRATIONS.md` and `.env.example` | Not available/tested here |
| Local Ollama daemon + actual pulled model | Only when Ollama provider is selected | `ONESHOT_*_OLLAMA_*` settings | No reachable real model verified; loopback inside Docker is different |

Avoid speculative packages: no automatic React install, Pydantic AI, scikit-learn, LangChain, MCP runtime or extra model SDK is justified by this candidate's current consumers. Installing them would not resolve the missing E2E and runtime gates.

## Windows PowerShell — prerequisite installation

Run this in an ordinary terminal with appropriate installer permissions. Validate the official installer / package version according to your security policy. Network access is required for first-time installation unless using approved cached artifacts.

```powershell
# Install uv using the official WinGet package, then open a new terminal if needed.
winget install --id astral-sh.uv -e
uv --version

# Install Node.js 22+ from your approved distribution (Node.js official installer
# or organization-managed package channel), then verify both binaries:
node --version
npm --version

# From the actual OneShot repository root:
uv python install 3.11
uv python find 3.11
Get-Content .python-version           # expected: 3.11

# FIRST authorized dependency-resolution run only, because this candidate
# lacks uv.lock. Resolve, inspect, approve and COMMIT the generated lock.
uv lock --python 3.11

# Repeatable clean installs must use the reviewed lock.
uv sync --locked --extra test --python 3.11
uv run --locked --python 3.11 python -c "import sys; assert sys.version_info[:2] == (3,11), sys.version"

Push-Location frontend
npm ci
npm test
npm run check
npm run build
Pop-Location

# Browser binaries are a separate Playwright installation requirement.
uv run --locked --python 3.11 python -m playwright install chromium
```

`uv sync` creates/uses the project `.venv`; `uv venv --python 3.11` is optional, not an additional dependency installation required by this project. `uv python pin 3.11` is unnecessary if `.python-version` already says `3.11`; use it only if an approved repository pin change is needed.

## Linux/macOS equivalent

```bash
# Install uv with an organization-approved package manager or official installer:
# curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
# Install and verify Node.js >=22 and npm separately.
node --version && npm --version
cd /path/to/actual/OneShot
uv python install 3.11
uv python find 3.11
uv lock --python 3.11       # ONE-TIME only; review and commit uv.lock
uv sync --locked --extra test --python 3.11
uv run --locked --python 3.11 python -c 'import sys; assert sys.version_info[:2] == (3,11), sys.version'
(cd frontend && npm ci && npm test && npm run check && npm run build)
uv run --locked --python 3.11 python -m playwright install chromium
# On supported CI Linux environments requiring browser OS libs, use:
# uv run --locked --python 3.11 python -m playwright install --with-deps chromium
```

**If the interpreter download fails:** check DNS, corporate proxy, GitHub access, and approved package mirrors. Do not run Python 3.13 tests and label them Python 3.11. In this audit `uv python install 3.11` returned exit 1 due DNS resolution; `uv lock --offline` returned exit 2 because 3.11 was not installed.

## Server-side configuration: never expose model tokens in frontend

For local server running on Windows, set the operator secrets in the PowerShell process environment (values shown are illustrative placeholders **not valid production secrets**):

```powershell
$env:ONESHOT_API_TOKEN = '<random-secret-generated-outside-source-control>'
$env:ONESHOT_BROWSER_PASSWORD = '<distinct-operator-password>'
$env:ONESHOT_DATA_DIR = './data'
$env:ONESHOT_PROVIDER = 'evidence'
uv run --locked --python 3.11 python -m uvicorn systems.api:create_app --factory --host 127.0.0.1 --port 8787 --workers 1
```

`.env.example` is a template, **not** an automatic local dotenv loader. Compose reads shell / `.env` interpolation values; the Python server reads process environment variables. For live System provider and optional Agent installation, configure only supported `ONESHOT_*` settings documented in `docs/MODEL_INTEGRATIONS.md`; verify selected model IDs, credentials, privacy approval, endpoint accessibility, response contracts and user-facing provider attribution. `ONESHOT_PROVIDER=evidence` is valid for truthful source-evidence operations but **not** for claiming semantic AI inference.

## Container build reproducibility — Root Cause: approved lock file missing

The **current Dockerfile** uses Python 3.11, pins the uv installer version,
requires `uv.lock`, and runs `uv sync --frozen` without an unlocked pip fallback.
A clean build therefore fails intentionally when the lock is missing. The
container's Python lock parity has **not** been executed or demonstrated.

Before shipping an image, resolve and review `uv.lock` under the actual Python
3.11-enabled authorized environment, then verify `npm ci`, `docker compose
config`, `docker compose build`, runtime health, restricted credentials, persisted
volume permissions, restart/recovery, and authenticated full-browser E2E.
Container `localhost` is not host Ollama: configure reachable routing explicitly.
Public multi-user deployment remains unapproved; preserve single-operator scope.

## Required full-system verification commands (do not treat diagnostics as VALID)

Run on the **authorized target checkout**, using the exact reviewed lock and appropriate dedicated test environment:

```bash
uv run --locked --python 3.11 python -m pytest -q             # diagnostic
(cd frontend && npm test && npm run check && npm run build)  # diagnostic
uv run --locked --python 3.11 python -m tests.e2e_http       # real HTTP diagnostic
uv run --locked --python 3.11 python -m tests.e2e_multi_provider_http  # LOCAL PROTOCOL RESPONDER ONLY
uv run --locked --python 3.11 python -m tests.e2e_browser    # required actual Chromium -> API
uv run --locked --python 3.11 python -m tests.e2e_presend    # required Chromium pre-send journey
uv run --locked --python 3.11 python -m tests.e2e_live_model # required live configured provider browser journey
```

**These commands DO NOT cover all documented workflows by themselves.** Refer to `WORKFLOW_E2E_MATRIX.csv` in the audit package. Missing full-browser tests for each applicable workflow, real-provider semantic evaluation and target Docker verification must be added/executed before saying VALID. A controlled provider-protocol responder is **not** a real OpenAI, Gemini or Ollama model. Desktop browser is in scope; mobile application build is explicitly excluded.

## Release verdict

Return `VALID` **only** if the complete declared approved workflow scope has real authenticated frontend-to-backend-to-persisted-result E2E evidence on the actual target environment, plus target Python 3.11/lock, real configured model tests for required semantic tasks, restart/recovery, security negative paths, and Docker deployment (when the release target uses Docker). If one required gate is reporting a `Root Cause`, is absent, skipped, or unexecuted, return `NOT VERIFIED` or `NOT VALID`, including the command, exit code, and the `Root Cause / Analyze / Causing / Analyzing` tag that describes the actual cause. Never call a passed unit test a production release.

References (patterns only): https://docs.astral.sh/uv/getting-started/installation/ ; https://docs.astral.sh/uv/guides/install-python/ ; https://docs.astral.sh/uv/concepts/projects/sync/ ; https://docs.astral.sh/uv/guides/integration/docker/ ; https://playwright.dev/python/docs/browsers ; https://docs.docker.com/build/building/best-practices/ .
