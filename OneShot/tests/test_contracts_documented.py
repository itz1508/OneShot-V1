"""Every Contract field must carry a human description (attribute docstring).

Enforces the pydantic-tools §Docstrings pattern on OneShot's wire shapes so
``/openapi.json`` always reflects what the field means, not just its type.
Future PRs that add an undocumented field fail here.
"""
from __future__ import annotations

import inspect

import systems.contracts as contracts_module
from systems.contracts import Contract


def _subclasses(cls):
    seen = {cls}
    pending = [cls]
    while pending:
        current = pending.pop()
        for sub in current.__subclasses__():
            if sub not in seen:
                seen.add(sub)
                pending.append(sub)
    return seen - {cls}


def test_every_contract_field_has_description():
    missing = []
    classes = sorted(_subclasses(Contract), key=lambda c: c.__name__)
    assert classes, 'contracts module exposed no Contract subclasses'
    for cls in classes:
        for name, info in cls.model_fields.items():
            if not (info.description or '').strip():
                missing.append(f'{cls.__name__}.{name}')
    assert not missing, (
        'Every Contract field needs an attribute docstring or Field(description=...). '
        'Missing: ' + ', '.join(missing)
    )


def test_openapi_carries_descriptions_via_use_attribute_docstrings():
    # Round-trip through the live FastAPI app so this test fails loudly if a
    # future change silently flips ``use_attribute_docstrings`` off.
    from fastapi.testclient import TestClient
    from systems.api import create_app
    from systems.settings import Settings
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(data_dir=Path(tmp), api_token='x' * 32)
        app = create_app(settings, auto_worker=False)
        with TestClient(app) as c:
            schema = c.get('/openapi.json').json()
    components = schema.get('components', {}).get('schemas', {})
    # JobCreate is the canonical contract: strict, cross-field validated, every
    # field documented. If descriptions survive the FastAPI serializer, they do
    # for every other contract too.
    assert 'JobCreate' in components, 'JobCreate missing from /openapi.json'
    properties = components['JobCreate']['properties']
    for name in ('operation', 'prompt_message_id', 'source_ids',
                 'expected_versions', 'idempotency_key'):
        assert name in properties
        assert properties[name].get('description', '').strip(), f'JobCreate.{name} lost its description'


def test_contract_subclass_has_class_docstring():
    for cls in sorted(_subclasses(Contract), key=lambda c: c.__name__):
        doc = inspect.getdoc(cls) or ''
        assert doc.strip(), f'{cls.__name__} is missing a class docstring'
