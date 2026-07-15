"""Unit tests for the AI generator response parser (no API calls)."""

import pytest
from engines.ai_generator import (
    _parse_response, GeneratedPitch,
    _apply_signature, _strip_trailing_signature,
)


def test_signature_appended_with_name_and_website():
    p = GeneratedPitch("Sub", "Hi Leyna,\n\nGreat post. Open to a chat?")
    r = _apply_signature(p, "Gabriel Nava", "https://gabrielnava.dev")
    assert r.body.splitlines()[-3:] == ["Best,", "Gabriel Nava", "https://gabrielnava.dev"]


def test_signature_strips_model_signoff_before_appending():
    """A sign-off the model added should be replaced, not duplicated."""
    p = GeneratedPitch("Sub", "Hi Leyna,\n\nGreat post.\n\nBest,\nGabriel Nava")
    r = _apply_signature(p, "Gabriel Nava", "https://gabrielnava.dev")
    assert r.body.count("Best,") == 1
    assert r.body.count("Gabriel Nava") == 1
    assert r.body.endswith("https://gabrielnava.dev")


def test_signature_without_website_omits_url_line():
    p = GeneratedPitch("Sub", "Hi Leyna,\n\nGreat post.")
    r = _apply_signature(p, "Gabriel Nava", "")
    assert r.body.splitlines()[-2:] == ["Best,", "Gabriel Nava"]
    assert "http" not in r.body


def test_signature_noop_when_no_identity():
    p = GeneratedPitch("Sub", "Hi Leyna,\n\nGreat post.")
    r = _apply_signature(p, "", "")
    assert r.body == p.body


def test_strip_trailing_signature_variants():
    assert _strip_trailing_signature("Body text.\n\nRegards,\nGabe") == "Body text."
    assert _strip_trailing_signature("Body text.\n\nCheers,") == "Body text."
    assert _strip_trailing_signature("Body text with no signoff.") == "Body text with no signoff."


def test_parse_well_formed_response():
    text = (
        "SUBJECT: Quick question about your work at Acme\n"
        "BODY:\n"
        "Hi John,\n\n"
        "Saw your recent post on distributed systems. Really resonated.\n"
        "I'm exploring roles in that space and would love a 15-min chat.\n\n"
        "Gabriel"
    )
    pitch = _parse_response(text)
    assert pitch.subject == "Quick question about your work at Acme"
    assert "John" in pitch.body
    assert "Gabriel" in pitch.body


def test_parse_case_insensitive_labels():
    text = "subject: My subject\nbody:\nHello there"
    pitch = _parse_response(text)
    assert pitch.subject == "My subject"
    assert pitch.body == "Hello there"


def test_parse_fallback_on_malformed():
    text = "Here is a random response with no labels."
    pitch = _parse_response(text)
    assert pitch.body == text.strip()


def test_generate_pitch_raises_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    from engines.ai_generator import generate_pitch
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        generate_pitch("John Doe", "Acme", "some context", api_key=None)
