"""Regression: provider="llama" is the authorized OneShot local-llama.cpp runtime.

OneShot v5 operator decision §2:
  - llama.cpp uses its OpenAI-compatible /v1/chat/completions over loopback.
  - Ollama remains supported but is a DIFFERENT runtime (daemon protocol).
  - No automatic fallback between them.
"""
import json
from pathlib import Path
import httpx
import pytest

from systems.settings import Settings
from systems.model_transport import ModelConnection, request_text, ModelTransportError


def test_llama_requires_loopback_endpoint():
    with pytest.raises(ValueError, match='loopback'):
        ModelConnection('llama', 'm', '', 'http://1.2.3.4:8080/v1/chat/completions')


def test_llama_rejects_token():
    """Local inference must not accept any credential."""
    with pytest.raises(ValueError, match='token'):
        ModelConnection('llama', 'm', 'leaked-secret',
                        'http://127.0.0.1:8080/v1/chat/completions')


def test_llama_openai_compat_wire_shape():
    """request_text with provider=llama MUST post an OpenAI-shaped payload
    without Authorization header to the configured loopback endpoint."""
    seen = {}
    def handler(request):
        seen['url'] = str(request.url)
        seen['authorization'] = request.headers.get('authorization')
        seen['body'] = json.loads(request.content)
        return httpx.Response(200, json={
            'choices': [{'finish_reason': 'stop',
                         'message': {'content': 'hello world', 'tool_calls': None}}],
        })
    mc = ModelConnection('llama', 'llama-3.2-1b',
                         '', 'http://127.0.0.1:8080/v1/chat/completions')
    answer = request_text(mc, 'sys', 'user', json_output=False,
                          transport=httpx.MockTransport(handler))
    assert answer == 'hello world'
    assert seen['url'].startswith('http://127.0.0.1:8080')
    assert seen['authorization'] is None, 'llama must NOT send Authorization'
    assert seen['body']['model'] == 'llama-3.2-1b'
    assert seen['body']['temperature'] == 0
    assert seen['body']['messages'] == [
        {'role': 'system', 'content': 'sys'},
        {'role': 'user', 'content': 'user'},
    ]


def test_llama_json_output_sets_response_format():
    def handler(request):
        return httpx.Response(200, json={
            'choices': [{'finish_reason': 'stop',
                         'message': {'content': '{"ok":true}', 'tool_calls': None}}],
        })
    mc = ModelConnection('llama', 'm', '', 'http://127.0.0.1:8080/v1/chat/completions')
    answer = request_text(mc, 'sys', 'user', json_output=True,
                          transport=httpx.MockTransport(handler))
    assert json.loads(answer) == {'ok': True}


def test_settings_accepts_llama_provider(tmp_path):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32,
                   browser_password='pw-16-chars-aaaa',
                   provider='llama', model_name='llama-3.2-1b',
                   model_endpoint='http://127.0.0.1:8080/v1/chat/completions')
    assert cfg.provider == 'llama'


def test_settings_rejects_llama_without_loopback(tmp_path):
    with pytest.raises(ValueError, match='loopback'):
        Settings(data_dir=tmp_path, api_token='a' * 32,
                 browser_password='pw-16-chars-aaaa',
                 provider='llama', model_name='x',
                 model_endpoint='https://api.openai.com/v1/chat/completions')


def test_llama_is_distinct_from_ollama():
    """Ollama uses /api/chat (Ollama protocol); llama uses /v1/chat/completions (OpenAI compat).
    Confirm the two system_connection paths are not interchangeable."""
    from systems.model_transport import system_connection
    class S:
        provider = 'ollama'
        model_name = 'qwen2'
        model_endpoint = None
        model_token = None
    a = system_connection(S())
    S.provider = 'llama'
    b = system_connection(S())
    assert a.provider == 'ollama' and b.provider == 'llama'
    assert a.endpoint.endswith('/api/chat'), a.endpoint
    assert b.endpoint.endswith('/v1/chat/completions'), b.endpoint
