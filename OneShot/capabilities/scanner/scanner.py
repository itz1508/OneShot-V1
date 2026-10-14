"""Scanner is a capability; read/view are its internal tools."""
from dataclasses import dataclass, field
from pathlib import PurePath
from .tools.read import read, TEXT
from .tools.view import view, ViewUnavailable, ViewFailed, ViewUnreadable

IMAGES = {'.png', '.jpg', '.jpeg', '.webp'}
# .gif stays declared Unsupported since no vision model path can read animated/palette-only GIFs reliably.
IMAGES_LEGACY_UNSUPPORTED = {'.gif'}


@dataclass(frozen=True)
class Observation:
    text: str
    coverage: str
    tool: str | None
    limitation: str | None
    provenance: dict | None = field(default=None)


def inspect(name: str, raw: bytes, *, vision_provider: str = 'none',
            vision_endpoint: str | None = None, vision_model: str | None = None,
            vision_timeout_seconds: float = 90.0, vision_transport=None) -> Observation:
    """Inspect a source. Image sources route through the vision reader when configured.

    All image failures map to a *precise* limitation code so the Worker can
    render an honest reason to the operator:

    * ``vision_not_configured`` -- no provider or missing endpoint/model.
    * ``vision_unreadable`` -- image failed admission (sniff/size/bounds).
    * ``vision_failed`` -- provider was called but did not return usable text.
    """
    suffix = PurePath(name).suffix.lower()
    if len(raw) > 1_000_000:
        return Observation('', 'blocked', None, 'Source byte limit exceeded')
    if suffix in TEXT:
        try:
            t = read(name, raw)
            return Observation(t, 'complete' if t.strip() else 'blocked', 'read',
                               None if t.strip() else 'Empty source')
        except ValueError as e:
            return Observation('', 'blocked', 'read', str(e))
    if suffix in IMAGES:
        try:
            result = view(name, raw, provider=vision_provider,
                          endpoint=vision_endpoint, model=vision_model,
                          timeout_seconds=vision_timeout_seconds,
                          transport=vision_transport)
            if not result['text'].strip():
                return Observation('', 'blocked', 'view', 'vision_failed:empty_response',
                                   provenance=result)
            return Observation(result['text'], 'complete', 'view', None, provenance=result)
        except ViewUnavailable as e:
            return Observation('', 'blocked', 'view', f'vision_not_configured:{e}')
        except ViewUnreadable as e:
            return Observation('', 'blocked', 'view', f'vision_unreadable:{e}')
        except ViewFailed as e:
            return Observation('', 'blocked', 'view', f'vision_failed:{e}')
    if suffix in IMAGES_LEGACY_UNSUPPORTED:
        return Observation('', 'blocked', None, 'Unsupported image format')
    return Observation('', 'blocked', None, 'Unsupported source format')
