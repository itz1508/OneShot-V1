# OneShot developer and release targets. All commands run from the repo root.

PYTHON_VENV := /tmp/oneshot-venv
EXPORT_FLAGS := --format requirements-txt --no-dev --no-editable --no-emit-workspace --no-emit-project

.PHONY: setup setup-frontend setup-browsers lint test conformance selfcheck test-frontend check build audit e2e all clean release sbom

setup:
	UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv sync --locked --extra test

setup-frontend:
	cd frontend && npm ci --no-audit --fund=false

setup-browsers:
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run playwright install chromium --with-deps

lint:
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run ruff check .

test:
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run --locked pytest

conformance:
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run --locked pytest tests/test_workflow_conformance.py -v

selfcheck:
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run --locked python -m scripts.selfcheck


test-frontend:
	cd frontend && npm test

check:
	cd frontend && npm run check

build:
	cd frontend && npm run build

audit:
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv export $(EXPORT_FLAGS) > /tmp/oneshot-req.txt
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run --with pip-audit pip-audit --requirement /tmp/oneshot-req.txt --disable-pip
	cd frontend && npm audit --omit=dev --audit-level=high

e2e:
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run --locked python -m tests.e2e_http
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run --locked python -m tests.e2e_presend
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run --locked python -m tests.e2e_browser

all: setup setup-frontend lint test conformance selfcheck test-frontend check build e2e

clean:
	rm -rf frontend/dist frontend/node_modules
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

sbom: setup setup-frontend
	@mkdir -p dist
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv export $(EXPORT_FLAGS) > /tmp/oneshot-req.txt
	UV_PROJECT_ENVIRONMENT=$(PYTHON_VENV) uv run --with pip-audit pip-audit --requirement /tmp/oneshot-req.txt --disable-pip --format cyclonedx-json --output dist/sbom.python.cyclonedx.json
	cd frontend && npm sbom --omit=dev --sbom-format=cyclonedx > ../dist/sbom.frontend.cyclonedx.json
	@echo "Wrote dist/sbom.python.cyclonedx.json and dist/sbom.frontend.cyclonedx.json"

release: all sbom
	@mkdir -p dist
	@tar --exclude="dist" --exclude="node_modules" --exclude="__pycache__" --exclude="*.pyc" --exclude=".pytest_cache" \
	    -czf dist/oneshot-release.tar.gz --transform "s,^\.,OneShot," .
	@echo "Wrote dist/oneshot-release.tar.gz"
	@sha256sum dist/oneshot-release.tar.gz dist/sbom.python.cyclonedx.json dist/sbom.frontend.cyclonedx.json
