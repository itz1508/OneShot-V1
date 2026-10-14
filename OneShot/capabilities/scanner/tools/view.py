"""Image inspection via a configured local llama.cpp vision provider.

The unconfigured path raises :class:`ViewUnavailable` and is the pipeline's
honest default. When a provider IS configured, failures raise distinct
exceptions carrying precise reasons -- the Scanner maps each to a limitation
code without ever reporting a successful read for a missing or malformed
image.
"""
from __future__ import annotations
import hashlib
import struct


class ViewUnavailable(RuntimeError):
    """No vision provider is configured. The System must say so, not synthesise."""


class ViewFailed(RuntimeError):
    """The provider was configured but the call could not produce usable text."""


class ViewUnreadable(RuntimeError):
    """The image bytes failed admission checks (sniff/size/dimension)."""


MAX_IMAGE_BYTES = 8_000_000
MAX_IMAGE_PIXELS = 20_000_000  # 20 megapixels guard against decompression bombs


def _sniff_mime(raw: bytes) -> str | None:
    """Return canonical MIME for PNG/JPEG/WebP, or None if unrecognised."""
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if raw[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if raw[:4] == b'RIFF' and raw[8:12] == b'WEBP':
        return 'image/webp'
    return None


def _dimensions(raw: bytes, mime: str) -> tuple[int, int]:
    """Return (width, height) WITHOUT invoking a full image decoder.

    Prefer parsing the file header; this keeps the admission check decoder-
    free so a crafted file cannot execute decompression work before the
    guard runs.
    """
    if mime == 'image/png':
        # IHDR chunk begins at byte 16 with width (4 bytes) + height (4 bytes).
        if len(raw) < 24:
            raise ViewUnreadable('Truncated PNG header')
        w, h = struct.unpack('>II', raw[16:24])
        return w, h
    if mime == 'image/jpeg':
        # Scan SOF markers for size.
        i = 2
        n = len(raw)
        while i < n - 9:
            if raw[i] != 0xFF:
                raise ViewUnreadable('Malformed JPEG stream')
            marker = raw[i + 1]
            # SOF markers (excluding non-size-bearing variants)
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                h, w = struct.unpack('>HH', raw[i + 5:i + 9])
                return w, h
            # Skip segment
            if i + 4 > n:
                raise ViewUnreadable('Truncated JPEG segment')
            seg_len = struct.unpack('>H', raw[i + 2:i + 4])[0]
            i += 2 + seg_len
        raise ViewUnreadable('JPEG start-of-frame not found')
    if mime == 'image/webp':
        # VP8 / VP8L / VP8X parsing per RIFF spec.
        if len(raw) < 30:
            raise ViewUnreadable('Truncated WebP header')
        chunk = raw[12:16]
        if chunk == b'VP8X':
            w = (raw[24] | (raw[25] << 8) | (raw[26] << 16)) + 1
            h = (raw[27] | (raw[28] << 8) | (raw[29] << 16)) + 1
            return w, h
        if chunk == b'VP8 ':
            if raw[23:26] != b'\x9d\x01\x2a':
                raise ViewUnreadable('Malformed VP8 start code')
            w = raw[26] | (raw[27] << 8)
            h = raw[28] | (raw[29] << 8)
            return w & 0x3FFF, h & 0x3FFF
        if chunk == b'VP8L':
            if raw[20] != 0x2F:
                raise ViewUnreadable('Malformed VP8L signature')
            bits = raw[21] | (raw[22] << 8) | (raw[23] << 16) | (raw[24] << 24)
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        raise ViewUnreadable('Unsupported WebP variant')
    raise ViewUnreadable('Unsupported image MIME')


def view(name: str, raw: bytes, *, provider: str = 'none',
         endpoint: str | None = None, model: str | None = None,
         timeout_seconds: float = 90.0,
         prompt: str = ('Transcribe every piece of text and label in this image, '
                        'exactly as written. If a region is unreadable, state so '
                        'explicitly. Do not add commentary.'),
         transport=None) -> dict:
    """Inspect an image. Return a provenance-bearing dict on success.

    The return shape is intentionally richer than :func:`capabilities.scanner.tools.read.read`
    so the Scanner can carry provenance (model_id, source_sha256, response_sha256,
    temperature, deterministic=False) through to the Worker trace. The Scanner
    adapter is responsible for mapping this payload into an ``Observation``.
    """
    if not raw:
        raise ViewUnreadable('Empty image bytes')
    if len(raw) > MAX_IMAGE_BYTES:
        raise ViewUnreadable(f'Image exceeds {MAX_IMAGE_BYTES}-byte limit')
    mime = _sniff_mime(raw)
    if mime is None:
        raise ViewUnreadable('Image signature did not match PNG/JPEG/WebP')
    try:
        w, h = _dimensions(raw, mime)
    except struct.error as exc:
        raise ViewUnreadable('Malformed image header') from exc
    if w * h > MAX_IMAGE_PIXELS or w <= 0 or h <= 0 or w > 32767 or h > 32767:
        raise ViewUnreadable(f'Image dimensions out of bounds (w={w}, h={h})')
    if provider == 'none' or not endpoint or not model:
        raise ViewUnavailable('No image-inspection provider configured')
    if provider != 'llama':
        raise ViewUnavailable(f'Unsupported vision provider: {provider!r}')
    from systems.model_transport import request_vision, ModelTransportError
    try:
        response = request_vision(endpoint, model, prompt, raw, mime,
                                   timeout_seconds=timeout_seconds, temperature=0.0,
                                   transport=transport)
    except ModelTransportError as exc:
        raise ViewFailed(f'Vision provider call failed: {exc}') from exc
    return {
        'text': response.text,
        'model_id': response.model_id,
        'temperature': response.temperature,
        'response_sha256': response.response_sha256,
        'source_sha256': hashlib.sha256(raw).hexdigest(),
        'source_mime': mime,
        'source_width': w,
        'source_height': h,
        'deterministic': False,
        'inspection_mode': 'visual',
    }
