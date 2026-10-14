"""Narrow, server-only text-generation adapters. No model can invoke OneShot tools.

Provider APIs are not interchangeable. Results from this module are *untrusted*
until existing System validators check their expected contracts/provenance.
"""
import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit
import httpx

MAX_RESPONSE_BYTES = 1_000_000
MAX_INPUT_CHARS = 160_000


class ModelTransportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelConnection:
    provider: str
    name: str
    token: str = ''
    endpoint: str = ''

    def __post_init__(self):
        if self.provider not in ('openai', 'model', 'gemini', 'ollama', 'llama'):
            raise ValueError('Unsupported model provider')
        if not self.name or len(self.name) > 160 or not re.fullmatch(r'[A-Za-z0-9._:/-]+', self.name):
            raise ValueError('Invalid model identifier')
        url = urlsplit(self.endpoint)
        if url.username or url.password or url.query or url.fragment or not url.hostname:
            raise ValueError('Model endpoint must not contain credentials, query or fragment')
        if self.provider in ('ollama', 'llama'):
            # Local inference binaries (ollama daemon, llama-server) can only be
            # contacted with explicit loopback routing. No token is accepted;
            # credentials never leave the host.
            if url.scheme != 'http' or url.hostname not in ('127.0.0.1', 'localhost', '::1'):
                raise ValueError(f'{self.provider} requires a local loopback HTTP endpoint')
            if self.token:
                raise ValueError(f'{self.provider} does not accept a token (local inference)')
        elif url.scheme != 'https':
            raise ValueError('Remote model transport requires HTTPS')
        if self.provider == 'gemini' and (url.hostname != 'generativelanguage.googleapis.com'
                                          or not url.path.startswith('/v1beta/models/')):
            raise ValueError('Gemini endpoint must use official generateContent API')
        if self.provider in ('model', 'openai', 'gemini') and not self.token:
            raise ValueError('Remote provider credentials required')


def request_text(connection: ModelConnection, system: str, user: str, *, json_output: bool,
                 transport: httpx.BaseTransport | None = None) -> str:
    """One provider call; no retries/fallback or tools, bounded response and strict extraction."""
    if len(system) + len(user) > MAX_INPUT_CHARS:
        raise ModelTransportError('Model input exceeds configured limit')
    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
    headers = {}
    if connection.provider in ('openai', 'model', 'llama'):
        # llama.cpp exposes an OpenAI-compatible /v1/chat/completions over loopback
        # and takes NO Authorization header. Payload shape stays identical.
        if connection.provider != 'llama':
            headers['Authorization'] = 'Bearer ' + connection.token
        payload = {'model': connection.name, 'temperature': 0, 'messages': messages}
        if json_output:
            payload['response_format'] = {'type': 'json_object'}
    elif connection.provider == 'gemini':
        headers['x-goog-api-key'] = connection.token
        payload = {
            'systemInstruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'user', 'parts': [{'text': user}]}],
        }
        if json_output:
            payload['generationConfig'] = {'responseMimeType': 'application/json'}
    else:
        payload = {'model': connection.name, 'messages': messages, 'stream': False,
                   'options': {'temperature': 0}}
        if json_output:
            payload['format'] = 'json'
    try:
        with httpx.Client(timeout=httpx.Timeout(35, connect=5), transport=transport,
                          follow_redirects=False, trust_env=False) as client:
            with client.stream('POST', connection.endpoint, headers=headers, json=payload) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ModelTransportError('Model output exceeded size limit')
                    data.extend(chunk)
        body = json.loads(data)
        if connection.provider in ('openai', 'model', 'llama'):
            choice = body['choices'][0]
            if choice.get('finish_reason') not in (None, 'stop'):
                raise ModelTransportError('Provider did not complete the requested output')
            if choice['message'].get('tool_calls'):
                raise ModelTransportError('Model tool calls are not authorized')
            answer = choice['message']['content']
        elif connection.provider == 'gemini':
            candidate = body['candidates'][0]
            if candidate.get('finishReason') not in (None, 'STOP'):
                raise ModelTransportError('Gemini generation was incomplete or blocked')
            answer = ''.join(p.get('text', '') for p in candidate['content']['parts'])
        else:
            if body.get('done') is not True:
                raise ModelTransportError('Ollama generation was not completed')
            if body['message'].get('tool_calls'):
                raise ModelTransportError('Model tool calls are not authorized')
            answer = body['message']['content']
    except ModelTransportError:
        raise
    except (httpx.HTTPError, ValueError, LookupError, TypeError, KeyError, IndexError, UnicodeError) as exc:
        raise ModelTransportError('Model transport or response contract failed') from exc
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 500_000:
        raise ModelTransportError('Model returned missing or oversized text')
    return answer


def system_connection(settings) -> ModelConnection:
    provider = 'openai' if settings.provider == 'openai' else settings.provider
    if provider == 'gemini':
        return ModelConnection('gemini', settings.model_name or '', settings.model_token or '',
                               f'https://generativelanguage.googleapis.com/v1beta/models/{settings.model_name}:generateContent')
    if provider == 'ollama':
        return ModelConnection('ollama', settings.model_name or '', '',
                               settings.model_endpoint or 'http://127.0.0.1:11434/api/chat')
    if provider == 'llama':
        # llama.cpp llama-server OpenAI-compatible endpoint, loopback only.
        return ModelConnection('llama', settings.model_name or '', '',
                               settings.model_endpoint or 'http://127.0.0.1:8080/v1/chat/completions')
    if provider in ('openai', 'model'):
        return ModelConnection(provider, settings.model_name or '', settings.model_token or '',
                               settings.model_endpoint or 'https://api.openai.com/v1/chat/completions')
    raise ValueError('Evidence mode has no model connection')


def installed_agents(settings) -> dict[str, ModelConnection]:
    """Only server-configured integrations. Never expose credentials to frontend."""
    entries = {}
    if settings.agent_openai_token and settings.agent_openai_model:
        entries['openai'] = ModelConnection('openai', settings.agent_openai_model,
            settings.agent_openai_token, 'https://api.openai.com/v1/chat/completions')
    if settings.agent_gemini_token and settings.agent_gemini_model:
        entries['gemini'] = ModelConnection('gemini', settings.agent_gemini_model,
            settings.agent_gemini_token,
            f'https://generativelanguage.googleapis.com/v1beta/models/{settings.agent_gemini_model}:generateContent')
    if settings.agent_ollama_model:
        entries['ollama'] = ModelConnection('ollama', settings.agent_ollama_model, '',
            settings.agent_ollama_endpoint or 'http://127.0.0.1:11434/api/chat')
    return entries



@dataclass(frozen=True)
class VisionResponse:
    """Narrow, read-only record of a single vision inference call."""

    text: str
    """Model's raw text response (whitespace-stripped, bounded)."""
    model_id: str
    """Model identifier as configured on the server-side settings."""
    temperature: float
    """Temperature used (0 for deterministic-attempt, honestly recorded)."""
    response_sha256: str
    """SHA-256 of the text response as returned."""


def request_vision(endpoint: str, model: str, prompt: str, image_bytes: bytes, mime: str,
                   *, timeout_seconds: float = 90.0, temperature: float = 0.0,
                   transport: httpx.BaseTransport | None = None) -> VisionResponse:
    """Call a local, loopback-only llama.cpp OpenAI-compatible /v1/chat/completions.

    Produces a raw text response bounded by MAX_RESPONSE_BYTES. The caller
    (Scanner) is responsible for provenance recording, SHA-256 of the source,
    and determinism accounting. This adapter deliberately does NOT retry.
    """
    import base64, hashlib
    from urllib.parse import urlsplit
    url = urlsplit(endpoint)
    if url.scheme not in ('http', 'https') or not url.hostname:
        raise ModelTransportError('Vision endpoint must be a well-formed loopback URL')
    if url.hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ModelTransportError('Vision provider must bind to a loopback address')
    if mime not in ('image/png', 'image/jpeg', 'image/webp'):
        raise ModelTransportError('Unsupported image MIME for vision inference')
    if not image_bytes:
        raise ModelTransportError('Empty image bytes')
    b64 = base64.b64encode(image_bytes).decode('ascii')
    payload = {
        'model': model,
        'temperature': float(temperature),
        'messages': [
            {'role': 'user', 'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{b64}'}},
            ]},
        ],
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(timeout_seconds, connect=5),
                          transport=transport, follow_redirects=False, trust_env=False) as client:
            with client.stream('POST', endpoint, json=payload) as response:
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                        raise ModelTransportError('Vision output exceeded size limit')
                    data.extend(chunk)
        body = json.loads(data)
        choice = body['choices'][0]
        if choice.get('finish_reason') not in (None, 'stop', 'length'):
            raise ModelTransportError('Vision provider did not complete the requested output')
        if choice['message'].get('tool_calls'):
            raise ModelTransportError('Vision provider tool calls are not authorized')
        answer = choice['message']['content']
    except ModelTransportError:
        raise
    except (httpx.HTTPError, ValueError, LookupError, TypeError, KeyError, IndexError, UnicodeError) as exc:
        raise ModelTransportError('Vision transport or response contract failed') from exc
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 500_000:
        raise ModelTransportError('Vision provider returned missing or oversized text')
    text = answer.strip()
    return VisionResponse(
        text=text,
        model_id=model,
        temperature=float(temperature),
        response_sha256=hashlib.sha256(text.encode('utf-8')).hexdigest(),
    )
