# OneShot-V1 review status

Prepared from `v10.01a132be-8e39-7468-a9cf-22d5da599902` on Windows, 2026-10-12 (America/Los_Angeles). The release source is `OneShot/`; the original export, tarball, checksums, and sidecars remain at this folder's root. The installed Python environment is `OneShot/.venv`; built web assets are `OneShot/frontend/dist`.

## Integrity

- All 174 entries in `oneshot-complete-release-2026-10-13-v6.0.11-SHA256SUMS.txt` matched the extracted files and tarball after installation and checks.
- The extracted release source files were not edited. Build and environment artifacts are outside the manifest.

## Toloka reference documents

- `OneShot/docs/evaluation/inventory.md` and `OneShot/docs/evaluation/fixture.md` were installed as project reference documents from the two new Toloka Markdown files with matching SHA-256 hashes. `OneShot/docs/evaluation/README.md` records their status and usage. Exact source copies also remain in `review/`.
- The full Downloads Markdown audit and cleanup disposition is in `review/DOWNLOAD_MD_AUDIT.md`.
- The ZIP archive comparison and reversible cleanup disposition is in `review/ZIP_AUDIT.md`, with member-level CSV inventories beside it. No ZIP content was imported into this release.
- The inventory describes 167 manifest entries and 170 archive members; this installed export has 174 checksum entries, including the tarball, and 173 packaged source files. Treat its counts as historical until reconciled with this export.
- The fixture document proposes candidate P09, P11, P12, and I05 inputs. It explicitly leaves P11 evaluation policy, real-model evidence, and E14 image acceptance unresolved. No candidate was installed as an acceptance gate or entered into `data/realmodel_evidence`.

## Executed checks

- Python 3.11.15: `uv sync --locked --extra test --python 3.11` passed.
- Release verifier: `uv run --locked --python 3.11 python scripts/verify_release.py` returned `NOT_VALID`; full gate record: `review/verify_release_last_run.json`.
- Verifier passed: pinned Ruff lint, selfcheck, workflow conformance (15 tests), Dockerfile contract (4 tests), HTTP integration, multi-provider protocol, Chromium setup, all nine declared deterministic E2E suites, and `docker compose config`.
- Direct Windows frontend commands passed: `npm.cmd ci --no-audit --fund=false`, `npm.cmd run check`, `npm.cmd test` (57/57), and `npm.cmd run build` (7 assets). `npm audit --omit=dev --audit-level=high` found 0 vulnerabilities.
- `uv run --locked --python 3.11 python -m scripts.benchmark_background --jobs 30` passed as a synthetic comparison: p95 foreground latency 143.226 ms baseline and 345.114 ms with background work. No production SLO is specified.
- WinML host probe ran; `review/winml-feasibility.json` records that `winml` is unavailable and the M-00 consumer decision is unresolved.

## Open findings

- The full Python pytest gate fails in two Windows tests: `test_destination_accepts_simple_name` asserts a POSIX-style path suffix, and `test_restored_instance_is_independent_of_source` cannot remove a source directory while its SQLite file is open. The remaining Python tests were not represented as a full passing suite.
- Four verifier frontend gates fail before execution because its Python `subprocess.run` launches `npm`, which Windows does not resolve as an executable here; the installed executable is `npm.cmd`. The same commands passed directly with `npm.cmd`.
- `tests.e2e_improvement_loop_closure` failed on its first standalone run at a browser recurring-defects assertion, then passed in the release verifier. The first failure log is `review/closure-first-run-failure.log`; the intermittent behavior remains uninvestigated.
- The Python `pip-audit` dependency scan was attempted but interrupted after it produced no result; no vulnerability verdict is claimed.
- Docker Compose configuration parsed, but the Docker daemon was unavailable, so no image build or running-container check occurred.
- Automatic approval review rejected recursive deletion of generated `.tmp`, `OneShot/data`, `.pytest_cache`, and `.ruff_cache` directories, including a second attempt on the exact `.pytest_cache` path. These test artifacts remain; release source file hashes are unchanged.
- Real-model and vision checks had no configured provider or model. P09, P12-real-model, I05-real-model, and the P11-semantic product decision remain blocked. No production deployment or live-model acceptance was performed. The verifier records `product_release_ready=false`.

This is an installed, checksum-verified review copy with generated test artifacts still present. It is not a product release approval. The executable local checks from the release and development docs were run where their prerequisites were available; historical procedures, destructive restore examples, credential-dependent checks, and deployment instructions were not treated as authorization to change external state.
