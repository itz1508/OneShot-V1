"""Auto-discovered capability tool catalogue.

Reads the already-shipped ``capabilities.*.tools`` modules and reports each
callable with its first docstring line and its availability. Availability is
intentionally shallow: the catalogue reports what the module explicitly
declares (``view`` raises ``ViewUnavailable`` on invocation; it is still a
registered tool). Dynamic availability — "is the HTTPS fetcher configured" —
is reported by the capability itself at call time, not at import time, which
preserves the existing contract that an unavailable tool returns an explicit
``blocked`` observation rather than disappearing from the registry.

``systems.api:/api/capabilities`` reads from this catalogue so the registry
stays in sync with the source tree. The response shape is a strict superset
of the previous hand-maintained dict: existing consumers (frontend, E2E)
continue to work.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from inspect import isfunction, getdoc
from typing import Any


@dataclass(frozen=True)
class ToolEntry:
    """One discovered capability tool."""

    name: str
    """Tool identifier, matches the exported function name."""
    description: str
    """First-line summary pulled from the function docstring."""
    available: bool
    """Whether the tool can run with the current OneShot deployment."""


def _first_line(obj: Any) -> str:
    # Prefer the function's own docstring; fall back to the module docstring
    # when the shipped tools (compact one-line functions) carry their summary
    # at module scope instead.
    doc = (getdoc(obj) or '').strip()
    if not doc:
        import sys
        module = sys.modules.get(getattr(obj, '__module__', ''))
        doc = ((getdoc(module) if module else '') or '').strip()
    return doc.splitlines()[0] if doc else ''


# Known runtime-availability signals the catalogue respects. The source of
# truth is still the capability itself at call time; these flags only affect
# the discovery response surface.
_UNAVAILABLE = {
    # ``view`` raises ``ViewUnavailable`` on every call because OneShot ships
    # no image-inspection provider. Mirrors the pre-catalogue hand-maintained
    # response that read ``view: unavailable``.
    ('scanner', 'view'): False,
}


def _tools_for(package_name: str) -> list[ToolEntry]:
    try:
        tools_mod = import_module(f'capabilities.{package_name}.tools')
    except ModuleNotFoundError:
        return []
    exported = getattr(tools_mod, '__all__', None)
    if exported is None:
        exported = [n for n in dir(tools_mod) if not n.startswith('_') and isfunction(getattr(tools_mod, n, None))]
    entries: list[ToolEntry] = []
    for name in exported:
        obj = getattr(tools_mod, name, None)
        if not isfunction(obj):
            continue
        entries.append(ToolEntry(
            name=name,
            description=_first_line(obj),
            available=_UNAVAILABLE.get((package_name, name), True),
        ))
    return entries


def discover() -> dict[str, list[ToolEntry]]:
    """Walk the three OneShot capability packages and report every tool.

    The key order is stable (scanner, researcher, advisor) so API consumers
    get a deterministic shape. Missing packages return an empty list rather
    than raising — the catalogue degrades gracefully if a capability is
    stripped from a packaging profile.
    """
    return {
        'scanner': _tools_for('scanner'),
        'researcher': _tools_for('researcher'),
        'advisor': _tools_for('advisor'),
    }


def capability_report(provider: str) -> dict[str, Any]:
    """Build the ``/api/capabilities`` response from the catalogue.

    ``provider`` is the configured ``ONESHOT_PROVIDER`` value; it decides the
    ``auto_generator.mode`` label. The shape is a strict superset of the
    previous hand-maintained response — every existing top-level key is still
    present with the same semantic value, plus each tool now carries a
    ``description`` and an explicit ``available`` bool.
    """
    discovered = discover()

    def _tool_map(entries: list[ToolEntry]) -> dict[str, dict[str, Any]]:
        return {e.name: {'available': e.available, 'description': e.description} for e in entries}

    scanner = _tool_map(discovered['scanner'])
    researcher = _tool_map(discovered['researcher'])
    advisor = _tool_map(discovered['advisor'])

    # Preserve legacy shape ``scanner.tools.<name>: 'available'|'unavailable'``
    # for existing consumers (frontend uses ``api.capabilities()``; E2E reads
    # /api/capabilities on login). The structured catalogue is additive.
    legacy_scanner = {name: ('available' if info['available'] else 'unavailable')
                      for name, info in scanner.items()}
    # Researcher reporting matches the previous hand-maintained labels: the
    # URL validator is validation-only (no fetching), extraction only works
    # for explicitly supplied HTML. The catalogue records this verbatim.
    legacy_researcher = {
        'web_browser': 'validation_only',
        'web_extraction': 'available_for_supplied_html',
    }
    # Legacy label kept stable for API consumers. The capability's single
    # tool is checklist preparation; the function export is `prepare`. The
    # historical response labeled it 'checklist' (the module), which matches
    # how operators refer to it. Preserve verbatim so pre-existing API clients
    # keep working; the richer per-function info is in body['catalog'].
    legacy_advisor_tools = ['checklist'] if 'prepare' in advisor else sorted(advisor.keys())

    return {
        # Legacy top-level keys (preserved verbatim):
        'scanner': {'tools': legacy_scanner},
        'researcher': legacy_researcher,
        'advisor': {'tools': legacy_advisor_tools},
        'auto_generator': {
            'provider': provider,
            'mode': 'evidence_packet' if provider == 'evidence' else 'model_generated',
        },
        # Catalogue addition — the structured per-tool description and
        # availability flag. Consumers (tests, future UI) read this.
        'catalog': {
            'scanner': scanner,
            'researcher': researcher,
            'advisor': advisor,
        },
    }
