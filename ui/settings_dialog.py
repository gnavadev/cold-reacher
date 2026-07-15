"""
Settings dialogs:
  - SettingsDialog:     API keys (Gemini/Hunter/ZeroBounce/Abstract) + Reacher URL.
  - InstructionsDialog: full editor for the AI system instructions.
  - UserInfoDialog:     signature name/website.
Everything is stored in a local JSON file (.keys.json) and never appears in source.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QDialogButtonBox, QGroupBox,
    QFormLayout, QPlainTextEdit,
)

_KEY_FILE = Path(".keys.json")


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------

def _load_keys() -> dict[str, str]:
    if _KEY_FILE.exists():
        try:
            return json.loads(_KEY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    # Fallback: read individual env vars
    return {
        "gemini":   os.getenv("GEMINI_API_KEY", ""),
        "hunter":   os.getenv("HUNTER_API_KEY", ""),
        "abstract": os.getenv("ABSTRACT_API_KEY", ""),
    }


def _save_keys(new_values: dict[str, str]) -> None:
    """Merge *new_values* into the existing key file (never drops other fields)."""
    keys: dict[str, str] = {}
    if _KEY_FILE.exists():
        try:
            keys = json.loads(_KEY_FILE.read_text(encoding="utf-8"))
        except Exception:
            keys = {}
    keys.update(new_values)
    _KEY_FILE.write_text(json.dumps(keys, indent=2), encoding="utf-8")


def load_all_keys() -> dict[str, str]:
    return _load_keys()


def save_all_keys(
    gemini: str,
    hunter: str,
    zerobounce: str,
    abstract: str,
    reacher: str = "",
) -> None:
    # Merges — user_name/website/instructions live in other dialogs and are kept.
    _save_keys({
        "gemini": gemini, "hunter": hunter,
        "zerobounce": zerobounce, "abstract": abstract,
        "reacher": reacher,
    })


def save_instructions(instructions: str) -> None:
    """Persist the custom LLM instructions (merges, preserving keys)."""
    _save_keys({"instructions": instructions})


def save_user_info(user_name: str, website: str) -> None:
    """Persist the signature name/website (merges, preserving keys)."""
    _save_keys({"user_name": user_name, "website": website})


# ---------------------------------------------------------------------------
# Reusable key-field widget
# ---------------------------------------------------------------------------

def _make_key_row(placeholder: str) -> tuple[QLineEdit, QPushButton]:
    """Returns (line_edit, show_btn) — caller arranges them."""
    edit = QLineEdit()
    edit.setEchoMode(QLineEdit.EchoMode.Password)
    edit.setPlaceholderText(placeholder)

    btn = QPushButton("Show")
    btn.setCheckable(True)
    btn.setFixedWidth(50)

    def _toggle(checked: bool) -> None:
        edit.setEchoMode(
            QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password
        )
        btn.setText("Hide" if checked else "Show")

    btn.toggled.connect(_toggle)
    return edit, btn


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(
        self,
        current_gemini: str = "",
        current_hunter: str = "",
        current_zerobounce: str = "",
        current_abstract: str = "",
        current_reacher: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Settings — API Keys")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)

        # ---- Reacher (self-hosted, top priority) ----
        reacher_group = QGroupBox(
            "Reacher  ★ Recommended — self-hosted, unlimited, works for Google/Microsoft"
        )
        reacher_layout = QFormLayout(reacher_group)
        self._reacher_edit = QLineEdit(current_reacher)
        self._reacher_edit.setPlaceholderText("http://your-oracle-ip:8080")
        reacher_layout.addRow("Server URL:", self._reacher_edit)
        reacher_layout.addRow(
            "",
            _info("Run setup_reacher.sh on an Oracle Cloud Free Tier ARM instance — then paste the URL here."),
        )
        root.addWidget(reacher_group)

        # ---- Gemini ----
        gemini_group = QGroupBox("Google Gemini  (AI pitch generation)")
        gemini_layout = QFormLayout(gemini_group)
        self._gemini_edit, gemini_show = _make_key_row("AIza…")
        self._gemini_edit.setText(current_gemini)
        row = QHBoxLayout()
        row.addWidget(self._gemini_edit)
        row.addWidget(gemini_show)
        gemini_layout.addRow("API Key:", row)
        gemini_layout.addRow(
            "",
            _info("Get a free key at console.cloud.google.com → Gemini API"),
        )
        root.addWidget(gemini_group)

        # ---- Hunter.io ----
        hunter_group = QGroupBox(
            "Hunter.io  (recommended — finds & verifies emails, works for Google/M365)"
        )
        hunter_layout = QFormLayout(hunter_group)
        self._hunter_edit, hunter_show = _make_key_row("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._hunter_edit.setText(current_hunter)
        row2 = QHBoxLayout()
        row2.addWidget(self._hunter_edit)
        row2.addWidget(hunter_show)
        hunter_layout.addRow("API Key:", row2)
        hunter_layout.addRow(
            "",
            _info("Free tier: 25 email finds/month — hunter.io/users/sign_up"),
        )
        root.addWidget(hunter_group)

        # ---- ZeroBounce ----
        zb_group = QGroupBox("ZeroBounce  (100 free verifications/month, no credit card)")
        zb_layout = QFormLayout(zb_group)
        self._zerobounce_edit, zb_show = _make_key_row("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._zerobounce_edit.setText(current_zerobounce)
        row_zb = QHBoxLayout()
        row_zb.addWidget(self._zerobounce_edit)
        row_zb.addWidget(zb_show)
        zb_layout.addRow("API Key:", row_zb)
        zb_layout.addRow(
            "",
            _info("Free signup (no CC): app.zerobounce.net — copy key from dashboard"),
        )
        root.addWidget(zb_group)

        # ---- Abstract Email Reputation ----
        abstract_group = QGroupBox(
            "Abstract Email Reputation  (fallback verifier — 100 free/month)"
        )
        abstract_layout = QFormLayout(abstract_group)
        self._abstract_edit, abstract_show = _make_key_row("xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
        self._abstract_edit.setText(current_abstract)
        row3 = QHBoxLayout()
        row3.addWidget(self._abstract_edit)
        row3.addWidget(abstract_show)
        abstract_layout.addRow("API Key:", row3)
        abstract_layout.addRow(
            "",
            _info("Use the key from the ‘Email Reputation’ product — app.abstractapi.com"),
        )
        root.addWidget(abstract_group)

        # ---- Buttons ----
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # -- Accessors --

    def reacher_url(self) -> str:
        return self._reacher_edit.text().strip().rstrip("/")

    def gemini_key(self) -> str:
        return self._gemini_edit.text().strip()

    def hunter_key(self) -> str:
        return self._hunter_edit.text().strip()

    def zerobounce_key(self) -> str:
        return self._zerobounce_edit.text().strip()

    def abstract_key(self) -> str:
        return self._abstract_edit.text().strip()


def _info(text: str) -> QLabel:
    lbl = QLabel(f'<a style="color:#888; font-size:10px;">{text}</a>')
    lbl.setWordWrap(True)
    return lbl


# ---------------------------------------------------------------------------
# Instructions dialog (separate Settings entry)
# ---------------------------------------------------------------------------

class InstructionsDialog(QDialog):
    """
    Full-control editor for the AI system instructions.

    The box is pre-filled with the current instructions (or the built-in default
    when none are saved), so the user always sees exactly what's in effect and
    can edit or fully replace them.
    """

    def __init__(self, current_instructions: str = "", default_text: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings — Instructions")
        self.setMinimumSize(640, 520)

        self._default_text = default_text

        root = QVBoxLayout(self)
        root.addWidget(QLabel(
            "These instructions tell the AI how to write every pitch. "
            "Edit them freely, or replace them entirely."
        ))

        self._edit = QPlainTextEdit(current_instructions or default_text)
        root.addWidget(self._edit, stretch=1)

        note = _info(
            "Tip: keep the SUBJECT:/BODY: output format and the ‘no signature’ rule — "
            "the app relies on them to parse the pitch and add your signature."
        )
        root.addWidget(note)

        btn_row = QHBoxLayout()
        reset_btn = QPushButton("Reset to Default")
        reset_btn.clicked.connect(self._reset_to_default)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _reset_to_default(self) -> None:
        self._edit.setPlainText(self._default_text)

    def instructions(self) -> str:
        return self._edit.toPlainText().strip()


# ---------------------------------------------------------------------------
# User Info dialog (separate Settings entry)
# ---------------------------------------------------------------------------

class UserInfoDialog(QDialog):
    """Your name and website — used to sign off generated pitches."""

    def __init__(self, current_user_name: str = "", current_website: str = "",
                 parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings — User Info")
        self.setMinimumWidth(460)

        root = QVBoxLayout(self)

        info_group = QGroupBox("Your Signature  (used to sign off generated emails)")
        form = QFormLayout(info_group)
        self._user_name_edit = QLineEdit(current_user_name)
        self._user_name_edit.setPlaceholderText("e.g. Gabriel Nava")
        form.addRow("Name:", self._user_name_edit)
        self._website_edit = QLineEdit(current_website)
        self._website_edit.setPlaceholderText("e.g. https://gabrielnava.dev  (optional)")
        form.addRow("Website:", self._website_edit)
        root.addWidget(info_group)

        root.addWidget(_info(
            "Every generated pitch ends with:  Best, / <name> / <website>. "
            "Leave the website blank to omit that line."
        ))

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def user_name(self) -> str:
        return self._user_name_edit.text().strip()

    def website(self) -> str:
        return self._website_edit.text().strip()
