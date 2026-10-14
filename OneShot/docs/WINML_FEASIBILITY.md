# OneShot — Windows ML feasibility status

**Status:** M-00 (consumer decision) is UNRESOLVED. M-01 (host inventory) is
`PREREQUISITE_MISSING` on the Linux build host used for this release: there is
no Windows x64 interpreter + `winml-cli` binary on this machine, and the
builder package explicitly says the probe must run on an approved Windows
target instead.

## What is implemented today

- `scripts/winml_feasibility.py` — read-only probe. On Linux it reports host
  OS/arch/python and `winml_binary_discovery: TOOL_MISSING`. On a Windows x64
  host with `winml` on PATH (installed into a **separate** Python 3.11 venv
  per `plans/OneShot_Machine_Systems_Development_Refactor_Plan.md` M-01) the
  probe runs `winml --version` and `winml sys --format json` and writes
  `data/winml/feasibility.json`.
- `tests/test_winml_feasibility.py` — asserts that on a non-Windows host the
  probe exits 0, writes a JSON report, and reports `PREREQUISITE_MISSING`
  rather than silently claiming success.
- No `winml-cli` entry in `pyproject.toml`, `Dockerfile`, or `uv.lock`. The
  WinML dependency chain (PyTorch, ONNX Runtime, provider SDKs) stays out of
  OneShot's Linux container.
- `scripts/verify_release.py` does **not** block the main-product `VALID`
  verdict on this probe. WinML gates are optional and reported with precise
  `SKIPPED_PREREQUISITE_MISSING` reasons together with a `Root Cause / Analyze / Causing / Analyzing` diagnostic tag, so every non-OK gate names its exact cause class and corrective action rather than a hollow `BLOCKED` verdict.

## What is NOT yet implemented

- M-02 model inspect/analyze — needs an approved model + Windows target.
- M-03 reproducible build pipeline — needs an approved dataset + hardware.
- M-04 inference boundary — needs the M-00 decision (A: build-only
  workshop vs B: Windows-local inference consumer). `winml run`/`winml serve`
  are documented as disabled upstream and MUST NOT be depended on.
- M-05 System/UI integration — depends on an approved M-00 feature with a
  real UI consumer in OneShot.
- M-06 full Windows product E2E — depends on all of the above.

## How to proceed when an approved Windows host is available

```powershell
uv --version
uv python install 3.11
uv venv .venv-winml --python 3.11
uv pip install --python .venv-winml\Scripts\python.exe winml-cli==<reviewed-pin>
.\.venv-winml\Scripts\python.exe -m scripts.winml_feasibility --winml .\.venv-winml\Scripts\winml.exe --strict
```

The probe emits `data/winml/feasibility.json` with host, EP enumeration (via
`winml sys --format json`), and the recorded M-00 decision status. The main
OneShot `VALID` verdict is independent of this file; see
`scripts/verify_release.py`.
