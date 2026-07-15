"""Unit tests for the CSV logger (uses a tmp_path fixture, no real CSV needed)."""

import pytest
from engines.logger import log_lead, load_leads, update_last_contact, COLUMNS


def test_log_creates_file(tmp_path):
    csv_file = tmp_path / "leads.csv"
    log_lead("Jane Doe", "Apple", "apple.com", "jane.doe@apple.com", "Valid",
             csv_path=csv_file)
    assert csv_file.exists()


def test_log_header_columns(tmp_path):
    csv_file = tmp_path / "leads.csv"
    log_lead("Jane Doe", "Apple", "apple.com", "jane.doe@apple.com", "Valid",
             csv_path=csv_file)
    rows = load_leads(csv_file)
    assert set(COLUMNS).issubset(set(rows[0].keys()))


def test_log_and_load_roundtrip(tmp_path):
    csv_file = tmp_path / "leads.csv"
    log_lead(
        name="Jane Doe",
        company="Apple",
        domain="apple.com",
        validated_email="jane.doe@apple.com",
        verification_status="Valid",
        email_subject="Hello",
        email_content="Body text",
        csv_path=csv_file,
    )
    rows = load_leads(csv_file)
    assert len(rows) == 1
    assert rows[0]["Name"] == "Jane Doe"
    assert rows[0]["Validated Email"] == "jane.doe@apple.com"


def test_load_returns_empty_when_file_absent(tmp_path):
    rows = load_leads(tmp_path / "nonexistent.csv")
    assert rows == []


def test_multiple_leads(tmp_path):
    csv_file = tmp_path / "leads.csv"
    for i in range(3):
        log_lead(f"Person {i}", "Corp", "corp.com", f"p{i}@corp.com", "Valid",
                 csv_path=csv_file)
    rows = load_leads(csv_file)
    assert len(rows) == 3


def test_update_last_contact(tmp_path):
    csv_file = tmp_path / "leads.csv"
    log_lead("Jane Doe", "Apple", "apple.com", "jane.doe@apple.com", "Valid",
             csv_path=csv_file)
    updated = update_last_contact("Jane Doe", "Apple", date="2026-05-17",
                                  csv_path=csv_file)
    assert updated is True
    rows = load_leads(csv_file)
    assert rows[0]["Last Contact Date"] == "2026-05-17"


def test_update_last_contact_not_found(tmp_path):
    csv_file = tmp_path / "leads.csv"
    log_lead("Jane Doe", "Apple", "apple.com", "jane.doe@apple.com", "Valid",
             csv_path=csv_file)
    updated = update_last_contact("Nobody", "Nowhere", csv_path=csv_file)
    assert updated is False


def test_csv_injection_is_neutralised(tmp_path):
    """Values starting with formula triggers get a leading apostrophe."""
    csv_file = tmp_path / "leads.csv"
    log_lead(
        name="=cmd|'/c calc'!A1",           # classic CSV-injection payload
        company="+SUM(1+1)",
        domain="apple.com",
        validated_email="jane@apple.com",
        verification_status="Valid",
        email_content="@evil",
        csv_path=csv_file,
    )
    rows = load_leads(csv_file)
    assert rows[0]["Name"].startswith("'=")
    assert rows[0]["Company"].startswith("'+")
    assert rows[0]["Email Content"].startswith("'@")


def test_normal_values_are_not_modified(tmp_path):
    """Safe values pass through untouched."""
    csv_file = tmp_path / "leads.csv"
    log_lead("Jane Doe", "Apple", "apple.com", "jane@apple.com", "Valid",
             email_content="Hi Jane, saw your post.", csv_path=csv_file)
    rows = load_leads(csv_file)
    assert rows[0]["Name"] == "Jane Doe"
    assert rows[0]["Email Content"] == "Hi Jane, saw your post."
