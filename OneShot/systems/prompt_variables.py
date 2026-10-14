"""Operator-approved ${name} variable resolver for prompt instructions.

Syntax rules (ADR-002b, operator-approved):

- ``${name}`` is the ONLY interpolation form.
- ``$$`` escapes a literal ``$``; any other ``$`` not followed by ``{name}``
  is kept verbatim.
- ``{`` and ``{{`` have NO special meaning; JSON, JSON Schema, and code remain
  untouched.
- Variable names match ``[A-Za-z_][A-Za-z0-9_]*``.
- Every reference MUST be declared in the version's ``variables_json`` schema.
- Every declared required variable MUST appear in ``values``.
- Resolution is one-pass; supplied values are NEVER re-interpolated. Untrusted
  text in a value cannot inject a new ``${foo}`` reference.
- Resolution does NOT mutate the published template; a new string is returned.
"""
from __future__ import annotations
from dataclasses import dataclass
import re


_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*\Z')
# Match ``$$`` (escape), ``${name}`` (reference), or a lone ``$`` (literal kept).
_TOKEN_RE = re.compile(r'\$\$|\$\{([A-Za-z_][A-Za-z0-9_]*)\}')


class VariableResolutionError(ValueError):
    """Raised with a precise, operator-visible reason."""


@dataclass(frozen=True)
class VariableDefinition:
    name: str
    required: bool = True
    description: str = ""
    max_length: int = 10_000

    def __post_init__(self):
        if not _IDENT_RE.match(self.name):
            raise VariableResolutionError(
                f"Variable name {self.name!r} must match [A-Za-z_][A-Za-z0-9_]*")
        if self.max_length < 1 or self.max_length > 100_000:
            raise VariableResolutionError('max_length out of bounds (1..100000)')


def load_definitions(variables_json: list) -> list:
    """Validate and return a list of :class:`VariableDefinition`."""
    if not isinstance(variables_json, list):
        raise VariableResolutionError('variables_json must be a list')
    out = []
    seen = set()
    for item in variables_json:
        if not isinstance(item, dict):
            raise VariableResolutionError('variable entry must be an object')
        name = item.get('name')
        if not isinstance(name, str):
            raise VariableResolutionError('variable name must be a string')
        if name in seen:
            raise VariableResolutionError(f'Duplicate variable {name!r}')
        seen.add(name)
        out.append(VariableDefinition(
            name=name,
            required=bool(item.get('required', True)),
            description=str(item.get('description', '')),
            max_length=int(item.get('max_length', 10_000)),
        ))
    return out


def find_references(template: str) -> list:
    """Return a list of ``${name}`` references in the template (deduped)."""
    if not isinstance(template, str):
        raise VariableResolutionError('template must be a string')
    seen = []
    for match in _TOKEN_RE.finditer(template):
        if match.group(0) == '$$':
            continue
        name = match.group(1)
        if name not in seen:
            seen.append(name)
    return seen


def resolve(template: str, definitions: list, values: dict) -> str:
    """Validate + render. Raises :class:`VariableResolutionError` on any issue."""
    if not isinstance(values, dict):
        raise VariableResolutionError('values must be an object')
    defined = {d.name: d for d in definitions}
    referenced = find_references(template)
    undeclared = [r for r in referenced if r not in defined]
    if undeclared:
        raise VariableResolutionError(
            f'Template references undeclared variables: {", ".join(sorted(undeclared))}')
    missing = [d.name for d in definitions if d.required and d.name not in values]
    if missing:
        raise VariableResolutionError(
            f'Missing required variables: {", ".join(sorted(missing))}')
    extras = [k for k in values if k not in defined]
    if extras:
        raise VariableResolutionError(
            f'Unknown variables supplied: {", ".join(sorted(extras))}')
    for defn in definitions:
        if defn.name in values:
            v = values[defn.name]
            if not isinstance(v, str):
                raise VariableResolutionError(
                    f'Variable {defn.name!r} must be a string (got {type(v).__name__})')
            if len(v) > defn.max_length:
                raise VariableResolutionError(
                    f'Variable {defn.name!r} exceeds max_length {defn.max_length}')

    def _sub(match):
        token = match.group(0)
        if token == '$$':
            return '$'
        name = match.group(1)
        return values.get(name, '')  # defined-and-optional-missing => empty

    return _TOKEN_RE.sub(_sub, template)
