"""Diagnostic-outcome vocabulary for human-visible reporting.

Operator directive (Phase 14, 2026-10-12): wherever a bare `BLOCKED` /
`Blocker` label was used as a *verdict* in release reports or verifier
output, surface the structured ``Root Cause / Analyze / Causing /
Analyzing`` vocabulary instead. The directive targets REPORTING only; it
does NOT rename:

- the ``jobs.status`` SQLite column value ``'blocked'``
- the ``job_blocked`` event kind
- the ``Observation.coverage='blocked'`` scanner taxonomy
- the ``startBlocker`` pre-send helper
- the ``Advisor.checklist.blockers`` list
- ``net::ERR_BLOCKED_BY_ADMINISTRATOR`` Chromium diagnostic

Those are protected architectural identifiers; renaming them would break
persisted rows, the UI enum, SSE replay, 100+ tests. The directive is a
*vocabulary layer* over the existing taxonomy, not a schema change.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any


# The four approved public-facing verbs replace the historical "BLOCKED" label.
_PHASE = {
    'root_cause': 'Root Cause',   # terminal; a precise reason the step cannot run
    'analyze':    'Analyze',      # waiting-for-operator action verb
    'causing':    'Causing',      # live effect-of-cause narration
    'analyzing':  'Analyzing',    # in-flight investigation narration
}


@dataclass(frozen=True)
class DiagnosticTag:
    """Structured replacement for a bare ``BLOCKED`` verdict."""

    phase: str                   # one of _PHASE keys
    cause_class: str             # e.g. 'MODEL_RUNTIME_UNAVAILABLE'
    missing_prerequisite: str    # exact missing thing (no hand-wave)
    corrective_action: str       # verb-first imperative sentence
    details: dict[str, Any]      # optional extra evidence

    def __post_init__(self):
        if self.phase not in _PHASE:
            raise ValueError(f'phase must be one of {sorted(_PHASE)}')
        if not self.cause_class.strip() or ' ' in self.cause_class:
            raise ValueError('cause_class must be a non-empty, space-free class name')
        if not self.missing_prerequisite.strip():
            raise ValueError('missing_prerequisite must be non-empty')
        if not self.corrective_action.strip():
            raise ValueError('corrective_action must be non-empty')

    @property
    def phase_label(self) -> str:
        return _PHASE[self.phase]

    def render_line(self) -> str:
        """One-line human-readable form; replaces a bare `BLOCKED: ...`."""
        return (f'{self.phase_label} — cause_class={self.cause_class}; '
                f'missing={self.missing_prerequisite}; '
                f'action={self.corrective_action}')

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload['phase_label'] = self.phase_label
        return payload


def root_cause(cause_class: str, missing_prerequisite: str,
               corrective_action: str, **details: Any) -> DiagnosticTag:
    return DiagnosticTag('root_cause', cause_class, missing_prerequisite,
                         corrective_action, dict(details))


def analyze(cause_class: str, missing_prerequisite: str,
            corrective_action: str, **details: Any) -> DiagnosticTag:
    return DiagnosticTag('analyze', cause_class, missing_prerequisite,
                         corrective_action, dict(details))


def causing(cause_class: str, missing_prerequisite: str,
            corrective_action: str, **details: Any) -> DiagnosticTag:
    return DiagnosticTag('causing', cause_class, missing_prerequisite,
                         corrective_action, dict(details))


def analyzing(cause_class: str, missing_prerequisite: str,
              corrective_action: str, **details: Any) -> DiagnosticTag:
    return DiagnosticTag('analyzing', cause_class, missing_prerequisite,
                         corrective_action, dict(details))


# Promote the structured tag onto a legacy gate record whose only verdict was
# ``SKIPPED_PREREQUISITE_MISSING`` + a ``missing_prerequisite`` string.
def promote_gate_record(gate: dict) -> dict:
    """Attach a Root-Cause-shaped diagnostic to a gate record.

    - Called by :mod:`scripts.verify_release` for every gate whose status is
      not ``OK``.
    - Returns a *copy* of ``gate`` with a new ``diagnostic`` entry; it does
      not mutate the input, and it does not change the ``status`` field.
    """
    if not isinstance(gate, dict):
        return gate
    out = dict(gate)
    status = out.get('status', '')
    if status == 'OK':
        return out
    missing = out.get('missing_prerequisite') or out.get('reason') or ''
    stderr_tail = out.get('stderr_tail', '')
    stdout_tail = out.get('stdout_tail', '')
    if status == 'SKIPPED_PREREQUISITE_MISSING':
        tag = analyze(
            cause_class='PREREQUISITE_MISSING',
            missing_prerequisite=missing or 'unspecified',
            corrective_action=f"Install or configure ‘{missing or 'the prerequisite'}’ and rerun the gate.",
            gate=out.get('gate'),
        )
    elif status == 'FAILED':
        tag = root_cause(
            cause_class='GATE_FAILED',
            missing_prerequisite=missing or 'exit code != 0',
            corrective_action=f"Inspect gate output and address its root cause: {stderr_tail[-200:] or stdout_tail[-200:]}",
            gate=out.get('gate'),
            exit_code=out.get('exit_code'),
        )
    else:
        tag = analyzing(
            cause_class='UNKNOWN_STATUS',
            missing_prerequisite=f'status={status}',
            corrective_action='Investigate why the gate reported a non-OK status.',
            gate=out.get('gate'),
        )
    out['diagnostic'] = tag.to_dict()
    out['diagnostic_line'] = tag.render_line()
    return out
