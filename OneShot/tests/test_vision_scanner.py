"""Admission + decoder-safety + limitation-code coverage for the vision reader."""
import struct, zlib
from capabilities.scanner import inspect
from capabilities.scanner.tools.view import (
    view, ViewUnavailable, ViewFailed, ViewUnreadable, _sniff_mime, _dimensions,
    MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS,
)
import pytest


def _tiny_png() -> bytes:
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>II', 2, 2) + b'\x08\x02\x00\x00\x00'
    ihdr = b'IHDR' + ihdr_data
    ihdr_chunk = struct.pack('>I', len(ihdr_data)) + ihdr + struct.pack('>I', zlib.crc32(ihdr))
    idat_data = zlib.compress(b'\x00\xff\x00\x00\x00\xff\x00\x00')
    idat = b'IDAT' + idat_data
    idat_chunk = struct.pack('>I', len(idat_data)) + idat + struct.pack('>I', zlib.crc32(idat))
    iend_chunk = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND'))
    return sig + ihdr_chunk + idat_chunk + iend_chunk


def _tiny_jpeg() -> bytes:
    return (b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
            b'\xff\xc0\x00\x11\x08\x00\x02\x00\x02\x03\x01\x11\x00\x02\x11\x01\x03\x11\x01'
            b'\xff\xd9')


def _tiny_webp_vp8l() -> bytes:
    # VP8L-encoded WebP (1x1); pad to clear the reader's 30-byte minimum.
    import struct as _s
    bits = (1 - 1) | ((1 - 1) << 14)
    vp8l_body = b'\x2f' + _s.pack('<I', bits) + b'\x00' * 20
    chunk = b'VP8L' + _s.pack('<I', len(vp8l_body)) + vp8l_body
    riff = b'RIFF' + _s.pack('<I', 4 + len(chunk)) + b'WEBP' + chunk
    return riff


def test_sniff_recognises_png_jpeg_webp():
    assert _sniff_mime(_tiny_png()) == 'image/png'
    assert _sniff_mime(_tiny_jpeg()) == 'image/jpeg'
    assert _sniff_mime(_tiny_webp_vp8l()) == 'image/webp'
    assert _sniff_mime(b'GIF89a') is None
    assert _sniff_mime(b'') is None


def test_dimensions_png_jpeg_webp():
    assert _dimensions(_tiny_png(), 'image/png') == (2, 2)
    assert _dimensions(_tiny_jpeg(), 'image/jpeg') == (2, 2)
    w, h = _dimensions(_tiny_webp_vp8l(), 'image/webp')
    assert w == 1 and h == 1


def test_view_unavailable_when_no_provider():
    with pytest.raises(ViewUnavailable):
        view('x.png', _tiny_png())


def test_view_unreadable_rejects_bad_signature():
    with pytest.raises(ViewUnreadable):
        view('x.png', b'this is not a PNG')


def test_view_unreadable_rejects_empty():
    with pytest.raises(ViewUnreadable):
        view('x.png', b'')


def test_view_rejects_oversize_pre_decode():
    oversized = _tiny_png() + b'\x00' * (MAX_IMAGE_BYTES + 1)
    with pytest.raises(ViewUnreadable):
        view('x.png', oversized)


def test_view_rejects_decompression_bomb():
    # Build a PNG header advertising absurd dimensions; MUST be rejected without
    # ever running the actual image decoder.
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>II', 50000, 50000) + b'\x08\x02\x00\x00\x00'
    ihdr = b'IHDR' + ihdr_data
    ihdr_chunk = struct.pack('>I', len(ihdr_data)) + ihdr + struct.pack('>I', zlib.crc32(ihdr))
    bomb = sig + ihdr_chunk
    with pytest.raises(ViewUnreadable):
        view('bomb.png', bomb)


def test_scanner_dispatches_images_to_view_with_limitation_codes():
    """Scanner Observation.limitation must carry the precise code."""
    # Unconfigured provider on a valid PNG -> vision_not_configured
    obs = inspect('fig.png', _tiny_png())
    assert obs.coverage == 'blocked'
    assert obs.limitation.startswith('vision_not_configured:'), obs
    # Invalid PNG bytes -> vision_unreadable
    obs = inspect('fig.png', b'definitely not a png')
    assert obs.limitation.startswith('vision_unreadable:'), obs
    # GIF (legacy unsupported, never routed through vision)
    obs = inspect('fig.gif', b'GIF89a')
    assert obs.coverage == 'blocked'
    assert 'Unsupported image format' in (obs.limitation or '')
