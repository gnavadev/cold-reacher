"""
Local CSV persistence engine.

Thread-safe append-only logger for lead lifecycle data.
No PySide6 imports.
"""

from __future__ import annotations

import csv
import threading
from datetime import datetime
from pathlib import Path

COLUMNS = [
    "Name",
    "Company",
    "Domain",
    "Validated Email",
    "Verification Status",
    "Timestamp",
    "Email Subject",
    "Email Content",
    "Last Contact Date",
]

_DEFAULT_PATH = Path("leads.csv")
_lock = threading.Lock()

# Characters that spreadsheet apps (Excel, Google Sheets, LibreOffice) treat as
# the start of a formula. Lead data comes from untrusted pasted LinkedIn text
# and AI output, so any cell beginning with one of these is neutralised with a
# leading apostrophe to prevent CSV / formula injection when the file is opened.
_FORMULA_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value: str) -> str:
    """Neutralise a value that would be interpreted as a spreadsheet formula."""
    if isinstance(value, str) and value and value[0] in _FORMULA_TRIGGERS:
        return "'" + value
    return value


def _ensure_header(path: Path) -> None:
    """Write the CSV header if the file is new or empty."""
    if not path.exists() or path.stat().st_size == 0:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()


def log_lead(
    name: str,
    company: str,
    domain: str,
    validated_email: str,
    verification_status: str,
    email_subject: str = "",
    email_content: str = "",
    last_contact_date: str = "",
    csv_path: Path | str = _DEFAULT_PATH,
) -> None:
    """Append one row to the CSV log.  Thread-safe."""
    path = Path(csv_path)
    row = {
        "Name": _sanitize_cell(name),
        "Company": _sanitize_cell(company),
        "Domain": _sanitize_cell(domain),
        "Validated Email": _sanitize_cell(validated_email),
        "Verification Status": _sanitize_cell(verification_status),
        "Timestamp": datetime.now().isoformat(timespec="seconds"),
        "Email Subject": _sanitize_cell(email_subject),
        "Email Content": _sanitize_cell(email_content),
        "Last Contact Date": _sanitize_cell(last_contact_date),
    }
    with _lock:
        _ensure_header(path)
        with open(path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writerow(row)


def load_leads(csv_path: Path | str = _DEFAULT_PATH) -> list[dict]:
    """Return all logged leads as a list of dicts.  Returns [] if file absent."""
    path = Path(csv_path)
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def update_last_contact(
    name: str,
    company: str,
    date: str | None = None,
    csv_path: Path | str = _DEFAULT_PATH,
) -> bool:
    """
    Update the Last Contact Date for the most recent row matching name+company.
    Rewrites the file atomically.  Returns True if a row was updated.
    """
    path = Path(csv_path)
    rows = load_leads(path)
    if not rows:
        return False

    contact_date = date or datetime.now().date().isoformat()
    updated = False
    # Walk in reverse so we update the most-recent match
    for row in reversed(rows):
        if row.get("Name") == name and row.get("Company") == company:
            row["Last Contact Date"] = contact_date
            updated = True
            break

    if updated:
        with _lock:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
    return updated
