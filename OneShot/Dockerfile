# Reproducible single-operator OneShot deployment; require reviewed uv.lock.
FROM node:22-slim AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run check && npm run build

FROM python:3.11-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"
WORKDIR /app
# uv bootstraps its own deterministic installer version. Lockfile is mandatory.
RUN python -m pip install --no-cache-dir uv==0.10.0
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --no-editable --no-install-project
COPY systems /app/systems
COPY capabilities /app/capabilities
RUN uv sync --frozen --no-dev --no-editable
COPY --from=frontend-build /build/frontend/dist /app/frontend/dist
RUN useradd -m -u 10001 oneshot && mkdir -p /data && chown -R 10001:10001 /app /data
USER 10001
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/ready', timeout=3)" || exit 1
EXPOSE 8787
CMD ["python", "-m", "uvicorn", "systems.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--workers", "1"]
