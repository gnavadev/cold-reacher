"""Unit tests for the permutation generator and validation types (no network)."""

import pytest
from engines.validator import (
    generate_permutations,
    VerificationStatus,
    find_valid_email,
)


# ---------------------------------------------------------------------------
# Permutation generation
# ---------------------------------------------------------------------------

def test_permutations_count():
    perms = generate_permutations("Jane", "Doe", "apple.com")
    assert len(perms) == 10


def test_permutations_no_duplicates():
    perms = generate_permutations("Jane", "Doe", "apple.com")
    assert len(perms) == len(set(perms))


def test_permutations_correct_domain():
    perms = generate_permutations("Jane", "Doe", "apple.com")
    for p in perms:
        assert p.endswith("@apple.com")


def test_permutations_include_common_patterns():
    perms = generate_permutations("Jane", "Doe", "apple.com")
    assert "jane.doe@apple.com" in perms
    assert "jdoe@apple.com" in perms
    assert "jane@apple.com" in perms


def test_permutations_lowercases_inputs():
    perms = generate_permutations("JANE", "DOE", "APPLE.COM")
    assert "jane.doe@apple.com" in perms


def test_permutations_first_pattern_is_first_last():
    """first.last@ should always be the top pattern (highest statistical hit rate)."""
    perms = generate_permutations("John", "Smith", "corp.com")
    assert perms[0] == "john.smith@corp.com"


# ---------------------------------------------------------------------------
# VerificationStatus enum
# ---------------------------------------------------------------------------

def test_verification_status_values():
    assert VerificationStatus.VALID        == "Valid"
    assert VerificationStatus.CATCH_ALL    == "Catch-all"
    assert VerificationStatus.UNVERIFIABLE == "Unverifiable"
    assert VerificationStatus.INVALID      == "Invalid"
    assert VerificationStatus.UNKNOWN      == "Unknown"


# ---------------------------------------------------------------------------
# Validation priority routing (mocked network calls)
# ---------------------------------------------------------------------------

def test_reacher_path_used_when_url_provided(monkeypatch):
    """When a Reacher URL is set it takes priority over everything."""
    sentinel = object()
    monkeypatch.setattr(
        "engines.validator._validate_via_reacher",
        lambda *a, **kw: sentinel,
    )
    result = find_valid_email("Jane", "Doe", "corp.com", reacher_url="http://1.2.3.4:8080")
    assert result is sentinel


def test_hunter_path_used_when_key_provided(monkeypatch):
    """When a Hunter key is present (no Reacher URL), Hunter is called."""
    sentinel = object()
    monkeypatch.setattr(
        "engines.validator._validate_via_hunter",
        lambda *a, **kw: sentinel,
    )
    result = find_valid_email("Jane", "Doe", "corp.com", hunter_key="fake-key")
    assert result is sentinel


def test_zerobounce_path_used_when_key_provided(monkeypatch):
    sentinel = object()
    monkeypatch.setattr("engines.validator._validate_via_zerobounce", lambda *a, **kw: sentinel)
    result = find_valid_email("Jane", "Doe", "corp.com", zerobounce_key="fake-key")
    assert result is sentinel


def test_abstract_path_used_when_only_abstract_key(monkeypatch):
    """When only an AbstractAPI key is set, _validate_via_abstract is called."""
    sentinel = object()
    monkeypatch.setattr(
        "engines.validator._validate_via_abstract",
        lambda *a, **kw: sentinel,
    )
    result = find_valid_email("Jane", "Doe", "corp.com", abstract_key="fake-key")
    assert result is sentinel


def test_smtp_path_used_when_no_keys(monkeypatch):
    """With nothing configured, SMTP is the last-resort fallback."""
    sentinel = object()
    monkeypatch.setattr(
        "engines.validator._validate_via_smtp",
        lambda *a, **kw: sentinel,
    )
    result = find_valid_email("Jane", "Doe", "corp.com")
    assert result is sentinel


def test_reacher_beats_hunter_and_abstract(monkeypatch):
    """Reacher URL takes priority even when all three are configured."""
    reacher_s  = object()
    hunter_s   = object()
    abstract_s = object()

    monkeypatch.setattr("engines.validator._validate_via_reacher",  lambda *a, **kw: reacher_s)
    monkeypatch.setattr("engines.validator._validate_via_hunter",   lambda *a, **kw: hunter_s)
    monkeypatch.setattr("engines.validator._validate_via_abstract", lambda *a, **kw: abstract_s)

    result = find_valid_email(
        "Jane", "Doe", "corp.com",
        reacher_url="http://1.2.3.4:8080",
        hunter_key="h-key",
        abstract_key="a-key",
    )
    assert result is reacher_s


def test_hunter_takes_priority_over_abstract(monkeypatch):
    """Hunter key takes priority over AbstractAPI when no Reacher URL set."""
    hunter_s   = object()
    abstract_s = object()

    monkeypatch.setattr("engines.validator._validate_via_hunter",   lambda *a, **kw: hunter_s)
    monkeypatch.setattr("engines.validator._validate_via_abstract", lambda *a, **kw: abstract_s)

    result = find_valid_email(
        "Jane", "Doe", "corp.com",
        hunter_key="h-key", abstract_key="a-key",
    )
    assert result is hunter_s
