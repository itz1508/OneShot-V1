"""Regression: BLOCKED verdicts replaced by Root Cause / Analyze / Causing / Analyzing."""
from pathlib import Path
import json
import pytest
from systems.diagnostic_tags import (
    DiagnosticTag, root_cause, analyze, causing, analyzing, promote_gate_record,
)


def test_phase_label_is_capitalised():
    assert root_cause('X', 'y', 'z').phase_label == 'Root Cause'
    assert analyze('X', 'y', 'z').phase_label == 'Analyze'
    assert causing('X', 'y', 'z').phase_label == 'Causing'
    assert analyzing('X', 'y', 'z').phase_label == 'Analyzing'


def test_render_line_structured_fields():
    tag = root_cause('MODEL_RUNTIME_UNAVAILABLE', 'llama-server not reachable',
                    'Start llama-server on 127.0.0.1:8080 and rerun.')
    line = tag.render_line()
    assert line.startswith('Root Cause \u2014 ')
    assert 'cause_class=MODEL_RUNTIME_UNAVAILABLE' in line
    assert 'missing=llama-server not reachable' in line
    assert 'action=Start llama-server on 127.0.0.1:8080 and rerun.' in line


def test_rejects_bare_label_in_cause_class():
    with pytest.raises(ValueError):
        DiagnosticTag('root_cause', 'HAS SPACES', 'x', 'y', {})


def test_rejects_unknown_phase():
    with pytest.raises(ValueError):
        DiagnosticTag('UNKNOWN', 'X', 'y', 'z', {})


def test_promote_gate_skipped_prereq_is_analyze():
    gate = {'gate': 'docker', 'status': 'SKIPPED_PREREQUISITE_MISSING',
            'missing_prerequisite': 'docker'}
    out = promote_gate_record(gate)
    assert out['status'] == 'SKIPPED_PREREQUISITE_MISSING'
    assert out['diagnostic']['phase_label'] == 'Analyze'
    assert out['diagnostic']['cause_class'] == 'PREREQUISITE_MISSING'
    assert out['diagnostic']['missing_prerequisite'] == 'docker'
    assert 'docker' in out['diagnostic']['corrective_action']
    assert out['diagnostic_line'].startswith('Analyze \u2014 ')


def test_promote_gate_failed_is_root_cause():
    gate = {'gate': 'ruff_lint', 'status': 'FAILED', 'exit_code': 2,
            'stderr_tail': 'ruff failed: xyz'}
    out = promote_gate_record(gate)
    assert out['diagnostic']['phase_label'] == 'Root Cause'
    assert out['diagnostic']['cause_class'] == 'GATE_FAILED'
    assert 'xyz' in out['diagnostic']['corrective_action']


def test_promote_gate_ok_untouched():
    gate = {'gate': 'ruff_lint', 'status': 'OK'}
    out = promote_gate_record(gate)
    assert 'diagnostic' not in out


def test_verifier_persists_tag_on_every_non_ok_gate():
    out_json = Path('/work/_final/data/verification/last_run.json')
    if not out_json.exists():
        pytest.skip('verify_release.py has not been run yet')
    data = json.loads(out_json.read_text())
    for gate in data['gates']:
        if gate['status'] == 'OK':
            assert 'diagnostic' not in gate
        else:
            assert 'diagnostic' in gate, gate
            d = gate['diagnostic']
            assert d['phase_label'] in {'Root Cause', 'Analyze', 'Causing', 'Analyzing'}
            assert d['cause_class'] and ' ' not in d['cause_class']
            assert d['missing_prerequisite']
            assert d['corrective_action']
            assert gate['diagnostic_line'].startswith(f"{d['phase_label']} \u2014 ")


def test_no_bare_blocked_verdict_in_shipped_docs():
    """User-facing *.md must not use a bare BLOCKED verdict word.
    Protected architectural identifiers (job status 'blocked', event kind
    'job_blocked', coverage='blocked', ERR_BLOCKED_BY_ADMINISTRATOR) are
    allowed; meta-prose about the replacement is also allowed."""
    import re
    root = Path('/work/_final')
    allowed = (
        "net::ERR_BLOCKED_BY_ADMINISTRATOR",
        'no bare `BLOCKED`',
        'no bare BLOCKED',
        '`BLOCKED`',
        "BLOCKED` label",
        "BLOCKED` entry",
        "BLOCKED` verdict",
        "BLOCKED LABEL",
        "replaced by Root Cause",
    )
    offenders = []
    for path in root.rglob('*.md'):
        if '/.git/' in str(path):
            continue
        text = path.read_text()
        for match in re.finditer(r'(?<![A-Za-z_])BLOCKED(?![A-Za-z_])', text):
            start = max(0, match.start() - 40)
            end = min(len(text), match.end() + 40)
            context = text[start:end]
            if any(s in context for s in allowed):
                continue
            offenders.append((str(path.relative_to(root)), context))
    assert not offenders, (
        'User-facing docs carry a bare `BLOCKED` verdict:\n'
        + '\n'.join(f'  {p}: ...{c}...' for p, c in offenders))
