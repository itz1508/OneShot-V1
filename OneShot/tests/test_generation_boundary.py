"""Generation is not an endpoint or an upstream workflow owner."""

import pytest
from pydantic import ValidationError

from capabilities.advisor.tools.checklist import Checklist, Item
from systems.auto_generator import Generated, ProviderError
from systems.generation import PreparedInput, Systems


class CaptureGenerator:
    def __init__(self, result=None):
        self.calls = []
        self.result = result or Generated(
            'evidence_packet', 'Evidence packet', 'evidence', ('No semantic verification',)
        )

    def run(self, sources, checklist, objective):
        self.calls.append((sources, checklist, objective))
        return self.result


def prepared(ready=True):
    return PreparedInput(
        sources=({'id': 'a', 'text': 'original inspected text'},),
        checklist=Checklist((Item('a', 'content', ready, 'read result'),)),
        objective='Prepare evidence',
    )


def test_generate_uses_only_prepared_information():
    capability = CaptureGenerator()
    result = Systems(capability).generate(prepared_input=prepared())
    assert result.content == 'Evidence packet'
    assert capability.calls == [
        ([{'id': 'a', 'text': 'original inspected text'}], prepared().checklist, 'Prepare evidence')
    ]


def test_generate_refuses_unprepared_context_without_call():
    capability = CaptureGenerator()
    with pytest.raises(ProviderError, match='readiness'):
        Systems(capability).generate(prepared_input=prepared(ready=False))
    assert capability.calls == []


def test_generate_rejects_unknown_context_shape():
    capability = CaptureGenerator()
    with pytest.raises(TypeError, match='PreparedInput'):
        Systems(capability).generate(prepared_input={'raw_source': 'unsafe'})
    assert capability.calls == []


@pytest.mark.parametrize('invalid', [
    Generated('model_generated', 'payload', 'evidence', ()),
    Generated('evidence_packet', '', 'evidence', ()),
    Generated('unknown', 'payload', 'evidence', ()),
])
def test_generate_refuses_invalid_artifact_contract(invalid):
    capability = CaptureGenerator(invalid)
    with pytest.raises(ValidationError):
        Systems(capability).generate(prepared_input=prepared())
