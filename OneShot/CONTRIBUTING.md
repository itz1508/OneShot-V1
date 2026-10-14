# Contributing to OneShot

OneShot is a single-operator, source-grounded workspace. Keep contributions **surgical** and **implementation-only** — no planning docs, no future features without a shipped consumer.

## Toolchain

- Python **3.11** via `uv` (strict `requires-python = ">=3.11,<3.12"`).
- Node.js **≥ 22** for the frontend.
- Playwright Chromium for the browser E2E (`uv run playwright install chromium --with-deps`).

## One-time setup

```bash
make setup           # uv sync --locked --extra test
make setup-frontend  # cd frontend && npm ci
make setup-browsers  # playwright install chromium + system deps
pre-commit install   # optional but recommended
```

## Writing changes

1. **Read before write.** `docs/WORKFLOWS.md` pins each workflow to the live code. `docs/TRACING.md` pins the event / span data model. `docs/UI_LIFECYCLE.md` pins the frontend state machine.
2. **Match an existing responsibility.** `systems/` owns authority and lifecycle; `capabilities/` owns delegated per-task computation; `frontend/` owns the UI projection; `scripts/` owns operator utilities. Do not add a new top-level directory without an approved owner.
3. **Keep docs implementation-only.** If a code change requires a doc, update the matching file in `docs/`. Do not add planning or "future" docs; the rule is "all docs must describe what is implemented".
4. **No new runtime dependencies** without an explicit consumer in `systems/` or `capabilities/`, an entry in `pyproject.toml`, and a passing `make audit`.
5. **Guard every mutation with a test.** Place Python tests under `tests/`; frontend tests under `frontend/tests/`. The suite must stay green on `make all`.

## Local verification (identical to CI)

```bash
make lint         # ruff, correctness-only rules
make test         # pytest (89+ cases)
make conformance  # workflow-to-code anchors
make selfcheck    # DB round-trip + file-store sanity + frontend build
make test-frontend
make check
make build
make audit        # pip-audit + npm audit (fails on high)
make e2e          # real Chromium / real HTTP / real pre-send
```

CI (`.github/workflows/ci.yml`) runs the same gates on every pull request.

## Release

```bash
make release      # all gates + dist/oneshot-release.tar.gz + SHA-256
```

A release is only valid if `make all` is green; a mismatched SHA-256 or missing artifact is a hard failure.

## Pre-commit hooks

`.pre-commit-config.yaml` enables trailing-whitespace, EOF-fixer, large-file guard, YAML/TOML syntax, merge-conflict markers, private-key detection, no-direct-commit-to-main, and `ruff --fix`. Install with `pre-commit install`.


## Contracts: every field has a one-line attribute docstring

`systems/contracts.py` opts into `use_attribute_docstrings=True`, so every field with a docstring under it flows into `/openapi.json`. `tests/test_contracts_documented.py` enforces this — a new field without an attribute docstring (or `Field(description=...)`) fails the build. Keep the docstring to one line that answers *what this value is*, not *how it is validated* (type hints already cover the latter).
