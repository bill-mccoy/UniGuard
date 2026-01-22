import pytest
from uniguard.emailer import _prepare_attachments, _render_verification_text, _render_verification_html


def test_prepare_attachments_none_or_empty():
    assert _prepare_attachments(None) is None
    assert _prepare_attachments([]) is None


def test_prepare_attachments_basic():
    attachments = [{"filename": "test.txt", "content": "hello", "mime_type": "text/plain"}]
    out = _prepare_attachments(attachments)
    assert isinstance(out, list)
    assert out[0]["Filename"] == "test.txt"
    assert out[0]["ContentType"] == "text/plain"
    assert out[0]["Base64Content"] is not None


def test_render_verification_contains_code():
    code = "ABC123"
    text = _render_verification_text(code, recipient_name="Test")
    assert code in text
    assert "Hola" in text
    html = _render_verification_html(code, recipient_name="Test")
    assert code in html
    assert "<html" in html
