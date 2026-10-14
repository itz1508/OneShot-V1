"""Runtime configuration; browser password and provider credentials remain server-side."""
from dataclasses import dataclass
from pathlib import Path
import os

@dataclass(frozen=True)
class Settings:
    data_dir: Path
    api_token: str
    provider: str = 'evidence'
    model_endpoint: str | None = None
    model_token: str | None = None
    model_name: str | None = None
    browser_password: str | None = None
    frontend_dir: Path | None = None
    system_background: bool = True
    agent_openai_token: str | None = None
    agent_openai_model: str | None = None
    agent_gemini_token: str | None = None
    agent_gemini_model: str | None = None
    agent_ollama_model: str | None = None
    agent_ollama_endpoint: str | None = None
    vision_provider: str = 'none'
    vision_endpoint: str | None = None
    vision_model: str | None = None
    vision_mmproj: str | None = None
    vision_weights_sha256: str | None = None
    vision_timeout_seconds: float = 90.0

    def __post_init__(self):
        if len(self.api_token) < 24 or self.api_token.startswith('replace-'):
            raise ValueError('Set strong ONESHOT_API_TOKEN')
        if self.browser_password is not None and (len(self.browser_password) < 16 or self.browser_password.startswith('replace-')):
            raise ValueError('Set strong ONESHOT_BROWSER_PASSWORD')
        if self.provider not in ('evidence', 'model', 'openai', 'gemini', 'ollama', 'llama'):
            raise ValueError('Unknown provider')
        if self.provider != 'evidence':
            from systems.model_transport import system_connection
            system_connection(self)
        if self.vision_provider not in ('none', 'llama'):
            raise ValueError("ONESHOT_VISION_PROVIDER must be one of 'none','llama'")
        if self.vision_provider == 'llama':
            if not self.vision_endpoint:
                raise ValueError('ONESHOT_VISION_ENDPOINT is required when vision_provider=llama')
            if not self.vision_model:
                raise ValueError('ONESHOT_VISION_MODEL is required when vision_provider=llama')
            # Loopback-only enforcement
            import ipaddress, urllib.parse
            parsed = urllib.parse.urlparse(self.vision_endpoint)
            if parsed.scheme not in ('http', 'https'):
                raise ValueError('ONESHOT_VISION_ENDPOINT must use http or https')
            host = parsed.hostname or ''
            try:
                ip = ipaddress.ip_address(host)
                if not ip.is_loopback:
                    raise ValueError('ONESHOT_VISION_ENDPOINT must bind to a loopback address')
            except ValueError as exc:
                if host not in ('localhost',):
                    raise ValueError(f'ONESHOT_VISION_ENDPOINT must be loopback (got host={host!r})') from exc
        from systems.model_transport import installed_agents
        installed_agents(self)  # validate all configured integrations at startup

    @classmethod
    def from_env(cls):
        f = os.getenv('ONESHOT_FRONTEND_DIST')
        setting = os.getenv('ONESHOT_SYSTEM_BACKGROUND','true').lower()
        if setting not in ('true','false','1','0','yes','no'):
            raise ValueError('ONESHOT_SYSTEM_BACKGROUND must be true or false')
        return cls(
            Path(os.getenv('ONESHOT_DATA_DIR', './data')).resolve(),
            os.getenv('ONESHOT_API_TOKEN', ''),
            os.getenv('ONESHOT_PROVIDER', 'evidence'),
            os.getenv('ONESHOT_MODEL_ENDPOINT'),
            os.getenv('ONESHOT_MODEL_TOKEN'),
            os.getenv('ONESHOT_MODEL_NAME'),
            os.getenv('ONESHOT_BROWSER_PASSWORD'),
            Path(f).resolve() if f else None,
            setting in ('1','true','yes'),
            os.getenv('ONESHOT_AGENT_OPENAI_TOKEN'),
            os.getenv('ONESHOT_AGENT_OPENAI_MODEL'),
            os.getenv('ONESHOT_AGENT_GEMINI_TOKEN'),
            os.getenv('ONESHOT_AGENT_GEMINI_MODEL'),
            os.getenv('ONESHOT_AGENT_OLLAMA_MODEL'),
            os.getenv('ONESHOT_AGENT_OLLAMA_ENDPOINT'),
            os.getenv('ONESHOT_VISION_PROVIDER', 'none'),
            os.getenv('ONESHOT_VISION_ENDPOINT'),
            os.getenv('ONESHOT_VISION_MODEL'),
            os.getenv('ONESHOT_VISION_MMPROJ'),
            os.getenv('ONESHOT_VISION_WEIGHTS_SHA256'),
            float(os.getenv('ONESHOT_VISION_TIMEOUT_SECONDS', '90')),
        )
