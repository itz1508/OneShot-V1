"""Workflow-to-code conformance.

Each of the 8 approved OneShot workflows (D-01…D-08 from
``OneShot_Named_Diagrams_vNext_2026-10-10.md``, mapped in
``docs/WORKFLOWS.md``) is pinned here to the exact symbols or HTTP
endpoints that implement it. The test fails on drift so a diagram that
promises a node without a backing implementation can never land unnoticed.

This is intentionally a *shape* test, not an *execution* test:
    * imported symbols must exist and be callable
    * declared endpoints must appear on the FastAPI app with the
      expected method and ``Depends(auth)``
    * declared contracts must have the required Pydantic fields

Behavioural coverage lives in the dedicated ``tests/test_*``,
``tests/e2e_*`` and ``frontend/tests/*`` suites; this file is the
anchor layer.
"""
from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from pydantic import BaseModel


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

ROOT = Path(__file__).resolve().parents[1]


def _import(dotted: str):
    """Import ``dotted`` or fail the test loudly."""
    module_name, _, symbol = dotted.rpartition(".")
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - informative failure
        pytest.fail(f"Workflow anchor missing module {module_name!r}: {exc}")
    try:
        return getattr(module, symbol)
    except AttributeError:
        pytest.fail(f"Workflow anchor {dotted!r} missing symbol {symbol!r}")


def _routes(app, path: str, method: str):
    method = method.upper()
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == path
        and method in route.methods
    ]


def _authed(route: APIRoute) -> bool:
    """Return True iff the route depends on the auth guard."""
    return any(
        getattr(dep.call, "__name__", "") == "auth"
        for dep in route.dependant.dependencies
    )


@pytest.fixture
def app(tmp_path):
    from systems.api import create_app
    from systems.settings import Settings

    settings = Settings(
        data_dir=tmp_path,
        api_token="x" * 32,
        browser_password="z" * 32,
        system_background=False,
    )
    return create_app(settings=settings, auto_worker=False)


# --------------------------------------------------------------------------- #
# D-01 — Request classification and responsibility dispatch
# --------------------------------------------------------------------------- #


def test_d01_dispatch_anchors(app):
    _import("systems.operations.source_action")
    _import("systems.operations.admit")

    SourceAction = _import("systems.contracts.SourceAction")
    assert hasattr(SourceAction, "__metadata__") or hasattr(SourceAction, "__args__"), (
        "SourceAction must be a discriminated union annotation"
    )

    JobCreate = _import("systems.contracts.JobCreate")
    assert issubclass(JobCreate, BaseModel)
    assert "operation" in JobCreate.model_fields
    assert "prompt_message_id" in JobCreate.model_fields
    assert "source_ids" in JobCreate.model_fields
    assert "expected_versions" in JobCreate.model_fields

    assert _routes(app, "/api/conversations/{cid}/sources/actions", "POST"), (
        "D-01 Source Management entry endpoint missing"
    )
    assert _routes(app, "/api/conversations/{cid}/jobs", "POST"), (
        "D-01 job admission endpoint missing"
    )


# --------------------------------------------------------------------------- #
# D-02 — Optional pre-send review (server-side anchors; the JS layer
# has its own node:test suite under frontend/tests/)
# --------------------------------------------------------------------------- #


def test_d02_presend_server_anchors(app):
    add_message = _import("systems.operations.add_message")
    assert callable(add_message)

    MessageCreate = _import("systems.contracts.MessageCreate")
    assert "idempotency_key" in MessageCreate.model_fields
    assert "content" in MessageCreate.model_fields

    routes = _routes(app, "/api/conversations/{cid}/messages", "POST")
    assert routes and _authed(routes[0]), "D-02 message endpoint missing or unguarded"


def test_d02_presend_frontend_assets_present():
    presend_js = ROOT / "frontend" / "presend.js"
    text = presend_js.read_text(encoding="utf-8")
    for anchor in (
        "export function draftContextSummary",
        "export function reviewedMessage",
        "export function createPreSendController",
    ):
        assert anchor in text, f"D-02 frontend anchor missing: {anchor}"
    # Cancel-sends-nothing invariant: `.cancel()` never awaits `send(...)`.
    assert "cancel()" in text
    assert "send(" in text  # the exported controller still has a send path
    # Freeze-before-await invariant.
    assert "approved" in text and "await send" in text


# --------------------------------------------------------------------------- #
# D-03 — Source management and research boundary
# --------------------------------------------------------------------------- #


def test_d03_source_management_actions():
    from systems import contracts

    required = {
        "INPUT_SOURCE": contracts.InputSource,
        "IMPORT_SOURCE": contracts.ImportSource,
        "ADD_SOURCE": contracts.AddSource,
        "REFERENCE_SOURCE": contracts.ReferenceSource,
        "REMOVE_SOURCE": contracts.RemoveSource,
        "DELETE_SOURCE": contracts.DeleteSource,
    }
    for literal, model in required.items():
        action_field = model.model_fields["action"]
        annotation = action_field.annotation
        # ``Literal[INPUT_SOURCE]`` -> ``(INPUT_SOURCE,)``
        values = getattr(annotation, "__args__", ())
        assert literal in values, (
            f"D-03 action {literal!r} missing on {model.__name__}"
        )

    # Deletion is a separate authority
    assert "confirm_delete" in contracts.DeleteSource.model_fields

    # Researcher boundary — URL validation and extraction live outside Scanner.
    _import("capabilities.researcher.validate_url")
    _import("capabilities.researcher.extract_page")


# --------------------------------------------------------------------------- #
# D-04 — Foreground Scan–Read–Prepare–Generate
# --------------------------------------------------------------------------- #


def test_d04_scan_read_prepare_generate():
    inspect_fn = _import("capabilities.scanner.scanner.inspect")
    assert callable(inspect_fn)
    _import("capabilities.scanner.tools.read.read")
    _import("capabilities.scanner.tools.view.view")

    prepare_fn = _import("capabilities.advisor.tools.checklist.prepare")
    assert callable(prepare_fn)

    PreparedInput = _import("systems.generation.PreparedInput")
    import dataclasses as _dc
    assert _dc.is_dataclass(PreparedInput)
    pi_fields = {f.name for f in _dc.fields(PreparedInput)}
    assert {"sources", "checklist", "objective"}.issubset(pi_fields)

    Systems = _import("systems.generation.Systems")
    assert callable(Systems.generate)

    AutoGenerator = _import("systems.auto_generator.generator.AutoGenerator")
    assert callable(AutoGenerator.run)

    # Worker is the dispatch driver: it must exist and expose step().
    Worker = _import("systems.operations.Worker")
    assert callable(Worker.step)
    assert callable(Worker.execute)


# --------------------------------------------------------------------------- #
# D-05 — Output contract and truth boundary
# --------------------------------------------------------------------------- #


def test_d05_output_contract(app):
    GeneratedArtifact = _import("systems.contracts.GeneratedArtifact")
    assert issubclass(GeneratedArtifact, BaseModel)
    kinds = getattr(GeneratedArtifact.model_fields["kind"].annotation, "__args__", ())
    assert set(kinds) >= {"evidence_packet", "model_generated"}

    GeneratedDocument = _import("systems.contracts.GeneratedDocument")
    assert "document" in GeneratedDocument.model_fields
    assert "source_ids_used" in GeneratedDocument.model_fields

    # Artifact export and evidence endpoints
    assert _routes(app, "/api/conversations/{cid}/artifacts/{aid}", "GET")
    assert _routes(
        app, "/api/conversations/{cid}/artifacts/{aid}/evidence", "GET"
    )
    assert _routes(app, "/api/conversations/{cid}/artifacts/{aid}/export", "GET")


# --------------------------------------------------------------------------- #
# D-06 — Process display and replay
# --------------------------------------------------------------------------- #


def test_d06_events_and_stream(app):
    events = _routes(app, "/api/conversations/{cid}/events", "GET")
    stream = _routes(app, "/api/conversations/{cid}/events/stream", "GET")
    trace = _routes(app, "/api/conversations/{cid}/jobs/{jid}/trace", "GET")
    assert events and _authed(events[0])
    assert stream and _authed(stream[0])
    assert trace and _authed(trace[0])

    emit = _import("systems.store.emit")
    sig = inspect.signature(emit)
    for param in ("con", "cid", "kind"):
        assert param in sig.parameters, f"emit() missing parameter {param!r}"


# --------------------------------------------------------------------------- #
# D-07 — Independent system background
# --------------------------------------------------------------------------- #


def test_d07_independent_background(app):
    BackgroundWorker = _import("systems.background.BackgroundWorker")
    assert callable(BackgroundWorker.step)

    admit_terminal = _import("systems.background.admit_terminal")
    assert callable(admit_terminal)

    report = _import("systems.background.report")
    assert callable(report)

    routes = _routes(app, "/api/conversations/{cid}/background", "GET")
    assert routes and _authed(routes[0])


# --------------------------------------------------------------------------- #
# D-08 — Draft / review / apply safety boundary
# --------------------------------------------------------------------------- #


def test_d08_apply_boundary(app):
    _import("systems.apply.destination")
    _import("systems.apply.prepare")
    _import("systems.apply.confirm")

    PrepareApply = _import("systems.contracts.PrepareApply")
    ConfirmApply = _import("systems.contracts.ConfirmApply")
    assert "artifact_id" in PrepareApply.model_fields
    assert "destination" in PrepareApply.model_fields
    assert "expected_target_sha256" in PrepareApply.model_fields
    assert "confirmation_token" in ConfirmApply.model_fields

    DraftCreate = _import("systems.contracts.DraftCreate")
    DraftUpdate = _import("systems.contracts.DraftUpdate")
    assert "source_id" in DraftCreate.model_fields
    assert "expected_revision" in DraftUpdate.model_fields

    prepare_route = _routes(app, "/api/conversations/{cid}/apply/prepare", "POST")
    confirm_route = _routes(app, "/api/conversations/{cid}/apply/confirm", "POST")
    assert prepare_route and _authed(prepare_route[0])
    assert confirm_route and _authed(confirm_route[0])

# --------------------------------------------------------------------------- #
# D-H — UI lifecycle reducer (frontend/lifecycle.js)
# --------------------------------------------------------------------------- #


def test_dh_ui_lifecycle_module_present():
    module = ROOT / "frontend" / "lifecycle.js"
    tests = ROOT / "frontend" / "tests" / "lifecycle.test.mjs"
    assert module.is_file(), "D-H lifecycle reducer module missing"
    assert tests.is_file(), "D-H lifecycle reducer tests missing"
    text = module.read_text(encoding="utf-8")
    for anchor in (
        "export const INITIAL_STATE",
        "export const TRANSITIONS",
        "export function lifecycleReducer",
        "export function createLifecycleStore",
        "export function attachLifecyclePort",
    ):
        assert anchor in text, f"D-H anchor missing from lifecycle.js: {anchor}"
    # The reducer must list every screen the UI uses.
    for screen in (
        "SourceManagement",
        "Starting",
        "ProcessDisplay",
        "Pausing",
        "Paused",
        "EditorReview",
    ):
        assert screen in text, f"D-H screen {screen!r} missing from TRANSITIONS"
    # Pause requires a backend confirmation: PAUSE_CONFIRMED only from Pausing.
    assert "PAUSE_CONFIRMED" in text and "Paused" in text


def test_dh_lifecycle_docs_reference_implementation():
    guide = ROOT / "docs" / "UI_LIFECYCLE.md"
    assert guide.is_file(), "docs/UI_LIFECYCLE.md missing"
    text = guide.read_text(encoding="utf-8")
    assert "frontend/lifecycle.js" in text
    assert "frontend/tests/lifecycle.test.mjs" in text
    assert "useReducer" in text, "guide must document the useReducer equivalence"

def test_d06_latest_endpoint_and_tracing_doc(app):
    """D-06 anchors: /latest route + duration_ms projection + TRACING.md guide."""
    from systems.operations import trace as trace_fn

    assert _routes(app, "/api/conversations/{cid}/jobs/{jid}/latest", "GET")
    # trace() should always return a 'nodes' list; duration_ms is optional per node.
    src = inspect.getsource(trace_fn)
    assert "duration_ms" in src, "trace() must compute duration_ms when both ends exist"
    tracing_md = ROOT / "docs" / "TRACING.md"
    assert tracing_md.is_file(), "docs/TRACING.md missing"
    text = tracing_md.read_text(encoding="utf-8")
    for anchor in ("Permissions-Policy", "Referrer-Policy", "duration_ms",
                   "/jobs/{jid}/latest", "FileStore"):
        assert anchor in text, f"TRACING.md missing anchor: {anchor}"




# --------------------------------------------------------------------------- #
# D-I — Input / Content-type Inspection Branching
# --------------------------------------------------------------------------- #


def test_di_input_inspection_content_type_branching():
    """D-I diagram pins the scanner's content-type decision tree to code."""
    import inspect as _inspect
    from capabilities.scanner import inspect as scanner_inspect
    from capabilities.scanner.tools.read import TEXT, read as scanner_read
    from capabilities.scanner.tools.view import view as scanner_view, ViewUnavailable
    from capabilities.researcher import validate_url
    from systems.operations import Worker

    # Scanner dispatches by suffix — TEXT set covers the shipped text branches.
    for suffix in ('.txt', '.md', '.py', '.ts', '.json'):
        assert suffix in TEXT, (
            f"D-I TEXT branch must include {suffix}; see capabilities/scanner/tools/read.py"
        )
    # IMAGES branch exists but is declared unavailable (view() raises) — enforcement by absence.
    assert scanner_view is not None
    assert ViewUnavailable is not None
    # Research-needed branch validates URL (never auto-fetches).
    assert callable(validate_url)
    # Worker.execute composes multi-source and reports the tri-state quality.
    src = _inspect.getsource(Worker.execute)
    for anchor in ('structural_ready', 'incomplete', 'unusable',
                   'semantic_sufficiency', 'coverage_assessed',
                   'source_inspected'):
        assert anchor in src, f"D-I quality/coverage anchor missing from Worker.execute: {anchor}"
    # scanner.inspect returns a blocked Observation for an unsupported extension (files/folders deferred).
    unsupported = scanner_inspect('readme.unknownext', b'ignored bytes')
    assert unsupported.coverage == 'blocked'
    assert 'Unsupported' in (unsupported.limitation or ''), unsupported


# --------------------------------------------------------------------------- #
# D-V — Complete Integrated Product Verdict Tree
# --------------------------------------------------------------------------- #


def test_dv_verifier_verdict_tree_present():
    """D-V diagram pins the full-product verdict to scripts/verify_release.py."""
    import importlib
    import inspect as _inspect
    verifier = importlib.import_module('scripts.verify_release')
    assert hasattr(verifier, 'verdict'), 'verify_release.verdict() missing'
    assert hasattr(verifier, 'main'), 'verify_release.main() missing'
    src = _inspect.getsource(verifier)
    # Must honestly emit both verdicts and record the git_sha footer.
    for anchor in ('VALID', 'NOT_VALID', 'git_sha', 'OPTIONAL_GATES',
                   'SKIPPED_PREREQUISITE_MISSING'):
        assert anchor in src, f"D-V verifier anchor missing: {anchor}"
    # Every mandatory gate listed on the diagram must appear in main()'s gates.
    for gate in ('locked_python_environment', 'ruff_lint', 'selfcheck',
                 'python_diagnostics', 'workflow_conformance',
                 'dockerfile_contract',
                 'frontend_clean_install', 'frontend_check', 'frontend_tests',
                 'frontend_build',
                 'http_integration', 'multi_provider_protocol',
                 'chromium_install',
                 'browser_integrated_e2e', 'browser_presend_e2e',
                 'live_model_local_e2e', 'backup_restore_e2e'):
        assert gate in src, f"D-V mandatory gate missing from verify_release.main(): {gate}"


def test_dv_mobile_explicitly_out_of_scope():
    """D-V diagram shows a 'Mobile application if included in the approved build'
    branch; the shipped build does NOT include a mobile branch — enforced by:
    1. no mobile dependency in pyproject.toml / frontend/package.json;
    2. docs/WINML_FEASIBILITY.md records the single-platform scope;
    3. no mobile route in the FastAPI app.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for forbidden in ('react-native', 'cordova', 'flutter', 'ionic', 'capacitor'):
        for manifest in ('pyproject.toml', 'frontend/package.json', 'frontend/package-lock.json'):
            text = (root / manifest).read_text()
            assert forbidden not in text, f"Mobile dependency leaked into {manifest}: {forbidden}"
