"""
Main application window — two-panel lead management dashboard + log tab.
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QSplitter,
    QListWidget, QListWidgetItem,
    QLabel, QLineEdit, QTextEdit, QPushButton,
    QFormLayout, QGroupBox, QTabWidget,
    QStatusBar, QMessageBox, QFileDialog,
)

from engines.logger import log_lead, load_leads, COLUMNS
from engines.ai_generator import default_instructions
from ui.workers import ValidationWorker, PitchWorker
from ui.settings_dialog import (
    SettingsDialog, InstructionsDialog, UserInfoDialog,
    load_all_keys, save_all_keys, save_instructions, save_user_info,
)

_CSV_PATH = Path("leads.csv")      # export / audit log (Export/Log button)
_STATE_PATH = Path("leads.json")   # full working state, auto-saved each session


# ---------------------------------------------------------------------------
# Small reusable helpers
# ---------------------------------------------------------------------------

def _mono(widget):
    """Apply a monospace font to *widget* and return it."""
    font = QFont("Consolas", 9)
    widget.setFont(font)
    return widget


def _readonly(widget):
    widget.setReadOnly(True)
    return widget


# ---------------------------------------------------------------------------
# Lead data container
# ---------------------------------------------------------------------------

class Lead:
    def __init__(self, first: str, last: str, domain: str):
        self.first = first
        self.last = last
        self.domain = domain
        self.company: str = ""
        self.context: str = ""
        self.validated_email: str = ""
        self.status: str = ""
        self.subject: str = ""
        self.pitch: str = ""

    @property
    def full_name(self) -> str:
        return f"{self.first} {self.last}"

    def display_label(self) -> str:
        return f"{self.full_name}  —  {self.domain}"

    def to_dict(self) -> dict:
        return {
            "first": self.first,
            "last": self.last,
            "domain": self.domain,
            "company": self.company,
            "context": self.context,
            "validated_email": self.validated_email,
            "status": self.status,
            "subject": self.subject,
            "pitch": self.pitch,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Lead":
        lead = cls(d.get("first", ""), d.get("last", ""), d.get("domain", ""))
        lead.company = d.get("company", "")
        lead.context = d.get("context", "")
        lead.validated_email = d.get("validated_email", "")
        lead.status = d.get("status", "")
        lead.subject = d.get("subject", "")
        lead.pitch = d.get("pitch", "")
        return lead


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Cold Reacher — AI Cold Email Tool")
        self.setMinimumSize(1100, 720)

        self._leads: list[Lead] = []
        self._current_lead: Lead | None = None
        self._active_workers: list = []   # keep references alive

        keys = load_all_keys()
        self._api_key        = keys.get("gemini", "")
        self._hunter_key     = keys.get("hunter", "")
        self._zerobounce_key = keys.get("zerobounce", "")
        self._abstract_key   = keys.get("abstract", "")
        self._reacher_url    = keys.get("reacher", "")
        self._user_name      = keys.get("user_name", "")
        self._website        = keys.get("website", "")
        self._instructions   = keys.get("instructions", "")

        self._build_menu()
        self._build_ui()
        self._load_state()

        # Auto-select the first lead so its details populate on open
        if self._leads:
            self._lead_list.setCurrentRow(0)

    # ------------------------------------------------------------------
    # Menu bar
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("File")
        export_action = QAction("Export CSV…", self)
        export_action.triggered.connect(self._export_csv)
        file_menu.addAction(export_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.quit)
        file_menu.addAction(quit_action)

        settings_menu = menu.addMenu("Settings")
        key_action = QAction("API Keys…", self)
        key_action.triggered.connect(self._open_settings)
        settings_menu.addAction(key_action)
        instr_action = QAction("Instructions…", self)
        instr_action.triggered.connect(self._open_instructions)
        settings_menu.addAction(instr_action)
        user_info_action = QAction("User Info…", self)
        user_info_action.triggered.connect(self._open_user_info)
        settings_menu.addAction(user_info_action)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        tabs.addTab(self._build_dashboard_tab(), "Lead Dashboard")
        tabs.addTab(self._build_log_tab(), "Live Logs")

        self.setStatusBar(QStatusBar())

    def _build_dashboard_tab(self) -> QWidget:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(8, 8, 8, 8)

        # ---- Add lead form (top bar) ----
        add_group = QGroupBox("Add Lead")
        add_form = QHBoxLayout(add_group)

        self._first_edit = QLineEdit()
        self._first_edit.setPlaceholderText("First name")
        self._last_edit = QLineEdit()
        self._last_edit.setPlaceholderText("Last name")
        self._domain_edit = QLineEdit()
        self._domain_edit.setPlaceholderText("company.com")
        self._company_edit = QLineEdit()
        self._company_edit.setPlaceholderText("Company name (optional)")

        add_btn = QPushButton("Add Lead")
        add_btn.clicked.connect(self._add_lead)
        add_btn.setDefault(True)

        for label, widget in [
            ("First:", self._first_edit),
            ("Last:", self._last_edit),
            ("Domain:", self._domain_edit),
            ("Company:", self._company_edit),
        ]:
            add_form.addWidget(QLabel(label))
            add_form.addWidget(widget)

        add_form.addWidget(add_btn)
        root_layout.addWidget(add_group)

        # ---- Splitter: lead list | detail panel ----
        splitter = QSplitter(Qt.Orientation.Horizontal)

        splitter.addWidget(self._build_lead_list_panel())
        splitter.addWidget(self._build_detail_panel())
        splitter.setSizes([280, 820])

        root_layout.addWidget(splitter, stretch=1)
        return root

    def _build_lead_list_panel(self) -> QWidget:
        panel = QGroupBox("Leads")
        layout = QVBoxLayout(panel)

        self._lead_list = QListWidget()
        self._lead_list.currentRowChanged.connect(self._on_lead_selected)
        layout.addWidget(self._lead_list)

        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self._remove_lead)
        layout.addWidget(remove_btn)

        return panel

    def _build_detail_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # Context input
        ctx_group = QGroupBox("LinkedIn Context (paste raw text)")
        ctx_layout = QVBoxLayout(ctx_group)
        self._context_edit = QTextEdit()
        self._context_edit.setPlaceholderText(
            "Paste anything copied from LinkedIn — posts, About section, experience. "
            "The AI will filter out noise automatically."
        )
        self._context_edit.setMinimumHeight(120)
        ctx_layout.addWidget(self._context_edit)
        layout.addWidget(ctx_group)

        # Action buttons
        btn_row = QHBoxLayout()
        self._validate_btn = QPushButton("Validate Email")
        self._validate_btn.clicked.connect(self._run_validation)
        self._pitch_btn = QPushButton("Generate Pitch")
        self._pitch_btn.clicked.connect(self._run_pitch)
        self._log_btn = QPushButton("Export / Log")
        self._log_btn.clicked.connect(self._log_current_lead)

        for btn in (self._validate_btn, self._pitch_btn, self._log_btn):
            btn_row.addWidget(btn)
        layout.addLayout(btn_row)

        # Results
        results_group = QGroupBox("Results")
        results_layout = QFormLayout(results_group)

        self._email_display = _readonly(QLineEdit())
        self._email_display.setPlaceholderText("—")
        self._status_display = _readonly(QLineEdit())
        self._status_display.setPlaceholderText("—")
        self._subject_display = _readonly(QLineEdit())
        self._subject_display.setPlaceholderText("—")

        results_layout.addRow("Validated Email:", self._email_display)
        results_layout.addRow("Status:", self._status_display)
        results_layout.addRow("Subject:", self._subject_display)
        layout.addWidget(results_group)

        # Pitch output
        pitch_group = QGroupBox("Generated Pitch")
        pitch_layout = QVBoxLayout(pitch_group)
        self._pitch_display = _readonly(_mono(QTextEdit()))
        self._pitch_display.setPlaceholderText("Pitch will appear here after generation…")
        self._pitch_display.setMinimumHeight(160)
        self._pitch_display.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self._pitch_display.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        pitch_layout.addWidget(self._pitch_display)

        copy_btn = QPushButton("Copy Pitch to Clipboard")
        copy_btn.clicked.connect(self._copy_pitch)
        pitch_layout.addWidget(copy_btn)
        layout.addWidget(pitch_group, stretch=1)

        return panel

    def _build_log_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        self._log_display = _mono(QTextEdit())
        self._log_display.setReadOnly(True)
        self._log_display.setPlaceholderText("System log messages will appear here…")
        layout.addWidget(self._log_display)

        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self._log_display.clear)
        layout.addWidget(clear_btn)
        return widget

    # ------------------------------------------------------------------
    # Lead list operations
    # ------------------------------------------------------------------

    def _add_lead(self) -> None:
        first = self._first_edit.text().strip()
        last = self._last_edit.text().strip()
        domain = self._domain_edit.text().strip().lstrip("@")
        company = self._company_edit.text().strip()

        if not first or not last or not domain:
            QMessageBox.warning(self, "Incomplete", "First name, last name, and domain are required.")
            return

        lead = Lead(first, last, domain)
        lead.company = company or domain
        self._leads.append(lead)

        item = QListWidgetItem(lead.display_label())
        self._lead_list.addItem(item)
        self._lead_list.setCurrentRow(len(self._leads) - 1)

        for edit in (self._first_edit, self._last_edit, self._domain_edit, self._company_edit):
            edit.clear()

        self._save_state()

    def _remove_lead(self) -> None:
        row = self._lead_list.currentRow()
        if row < 0:
            return
        removed = self._leads.pop(row)
        if self._current_lead is removed:
            self._current_lead = None
        self._lead_list.takeItem(row)
        if self._leads:
            self._lead_list.setCurrentRow(min(row, len(self._leads) - 1))
        else:
            self._clear_detail_panel()
            self._current_lead = None
        self._save_state()

    def _on_lead_selected(self, row: int) -> None:
        if row < 0 or row >= len(self._leads):
            return
        # Save current context before switching
        if self._current_lead is not None:
            self._current_lead.context = self._context_edit.toPlainText()

        self._current_lead = self._leads[row]
        lead = self._current_lead

        self._context_edit.setPlainText(lead.context)
        self._email_display.setText(lead.validated_email)
        self._status_display.setText(lead.status)
        self._subject_display.setText(lead.subject)
        self._pitch_display.setPlainText(lead.pitch)

    def _clear_detail_panel(self) -> None:
        for w in (self._context_edit, self._pitch_display):
            w.clear()
        for w in (self._email_display, self._status_display,
                  self._subject_display):
            w.clear()

    # ------------------------------------------------------------------
    # Background workers
    # ------------------------------------------------------------------

    def _require_lead(self) -> Lead | None:
        if self._current_lead is None:
            QMessageBox.information(self, "No Lead", "Select or add a lead first.")
        return self._current_lead

    def _run_validation(self) -> None:
        lead = self._require_lead()
        if lead is None:
            return

        self._validate_btn.setEnabled(False)
        self._append_log(f"[INFO] Starting validation for {lead.full_name} @ {lead.domain}")

        worker = ValidationWorker(
            lead.first, lead.last, lead.domain,
            reacher_url=self._reacher_url,
            hunter_key=self._hunter_key,
            zerobounce_key=self._zerobounce_key,
            abstract_key=self._abstract_key,
        )
        worker.log_message.connect(self._append_log)
        worker.result_ready.connect(lambda r: self._on_validation_done(r, lead))
        worker.finished.connect(lambda: self._validate_btn.setEnabled(True))
        self._active_workers.append(worker)
        worker.finished.connect(
            lambda w=worker: self._active_workers.remove(w)
            if w in self._active_workers else None
        )
        worker.start()

    def _on_validation_done(self, result, lead: Lead) -> None:
        if result is None:
            self._append_log("[WARN] No valid email found for any permutation.")
            self._status_display.setText("Not found")
            lead.status = "Not found"
            self._save_state()
            return

        lead.validated_email = result.email
        lead.status = result.status.value
        self._email_display.setText(result.email)
        self._status_display.setText(result.status.value)
        self.statusBar().showMessage(f"Email validated: {result.email}", 5000)
        self._save_state()

    def _run_pitch(self) -> None:
        lead = self._require_lead()
        if lead is None:
            return

        if not self._api_key:
            QMessageBox.warning(
                self, "No API Key",
                "Set your Gemini API key via Settings → Gemini API Key…"
            )
            return

        # Snapshot context before thread starts
        lead.context = self._context_edit.toPlainText()
        if not lead.context.strip():
            QMessageBox.information(
                self, "No Context",
                "Paste some LinkedIn context before generating a pitch."
            )
            return

        self._pitch_btn.setEnabled(False)
        self._append_log(f"[INFO] Generating pitch for {lead.full_name} at {lead.company}…")

        worker = PitchWorker(
            lead.full_name, lead.company, lead.context, self._api_key,
            sender_name=self._user_name,
            sender_website=self._website,
            extra_instructions=self._instructions,
        )
        worker.log_message.connect(self._append_log)
        worker.result_ready.connect(lambda p: self._on_pitch_done(p, lead))
        worker.error.connect(lambda e: QMessageBox.critical(self, "Generation Error", e))
        worker.finished.connect(lambda: self._pitch_btn.setEnabled(True))
        self._active_workers.append(worker)
        worker.finished.connect(
            lambda w=worker: self._active_workers.remove(w)
            if w in self._active_workers else None
        )
        worker.start()

    def _on_pitch_done(self, pitch, lead: Lead) -> None:
        lead.subject = pitch.subject
        lead.pitch = pitch.body
        self._subject_display.setText(pitch.subject)
        self._pitch_display.setPlainText(pitch.body)
        self._pitch_display.verticalScrollBar().setValue(0)   # show from the top
        self.statusBar().showMessage("Pitch generated.", 5000)
        self._save_state()

    # ------------------------------------------------------------------
    # Logging & export
    # ------------------------------------------------------------------

    def _append_log(self, message: str) -> None:
        self._log_display.append(message)

    def _log_current_lead(self) -> None:
        lead = self._require_lead()
        if lead is None:
            return

        lead.context = self._context_edit.toPlainText()
        if not lead.validated_email:
            QMessageBox.information(
                self, "Nothing to Log",
                "Validate the email before logging — at minimum the email address is required."
            )
            return

        log_lead(
            name=lead.full_name,
            company=lead.company,
            domain=lead.domain,
            validated_email=lead.validated_email,
            verification_status=lead.status,
            email_subject=lead.subject,
            email_content=lead.pitch,
            csv_path=_CSV_PATH,
        )
        self._append_log(f"[INFO] Lead logged to {_CSV_PATH}: {lead.full_name}")
        self.statusBar().showMessage(f"Logged {lead.full_name} to {_CSV_PATH}", 5000)

    def _export_csv(self) -> None:
        dest, _ = QFileDialog.getSaveFileName(
            self, "Export CSV", "leads_export.csv", "CSV Files (*.csv)"
        )
        if not dest:
            return
        rows = load_leads(_CSV_PATH)
        if not rows:
            QMessageBox.information(self, "Empty", "No logged leads to export yet.")
            return
        import csv
        with open(dest, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=COLUMNS)
            writer.writeheader()
            writer.writerows(rows)
        self.statusBar().showMessage(f"Exported {len(rows)} rows to {dest}", 5000)

    def _copy_pitch(self) -> None:
        text = self._pitch_display.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.statusBar().showMessage("Pitch copied to clipboard.", 3000)

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _open_settings(self) -> None:
        dlg = SettingsDialog(
            current_gemini=self._api_key,
            current_hunter=self._hunter_key,
            current_zerobounce=self._zerobounce_key,
            current_abstract=self._abstract_key,
            current_reacher=self._reacher_url,
            parent=self,
        )
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._api_key        = dlg.gemini_key()
            self._hunter_key     = dlg.hunter_key()
            self._zerobounce_key = dlg.zerobounce_key()
            self._abstract_key   = dlg.abstract_key()
            self._reacher_url    = dlg.reacher_url()
            save_all_keys(
                self._api_key, self._hunter_key,
                self._zerobounce_key, self._abstract_key,
                self._reacher_url,
            )
            self.statusBar().showMessage("API keys saved.", 3000)

    def _open_instructions(self) -> None:
        dlg = InstructionsDialog(
            current_instructions=self._instructions,
            default_text=default_instructions(),
            parent=self,
        )
        if dlg.exec() == InstructionsDialog.DialogCode.Accepted:
            self._instructions = dlg.instructions()
            save_instructions(self._instructions)
            self.statusBar().showMessage("Instructions saved.", 3000)

    def _open_user_info(self) -> None:
        dlg = UserInfoDialog(
            current_user_name=self._user_name,
            current_website=self._website,
            parent=self,
        )
        if dlg.exec() == UserInfoDialog.DialogCode.Accepted:
            self._user_name = dlg.user_name()
            self._website   = dlg.website()
            save_user_info(self._user_name, self._website)
            self.statusBar().showMessage("User info saved.", 3000)

    # ------------------------------------------------------------------
    # Session persistence — full working state (leads.json)
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Write all leads (context, email, pitch, everything) to leads.json."""
        # Snapshot the editor's current text into the active lead first
        if self._current_lead is not None:
            self._current_lead.context = self._context_edit.toPlainText()
        try:
            data = [lead.to_dict() for lead in self._leads]
            _STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            self._append_log(f"[WARN] Could not save session state: {exc}")

    def _load_state(self) -> None:
        """Restore leads from leads.json; fall back to the CSV log on first run."""
        if _STATE_PATH.exists():
            try:
                data = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
            except Exception as exc:
                self._append_log(f"[WARN] Could not read {_STATE_PATH}: {exc}")
                data = []
            for d in data:
                lead = Lead.from_dict(d)
                if not lead.first or not lead.domain:
                    continue
                self._leads.append(lead)
                self._lead_list.addItem(QListWidgetItem(lead.display_label()))
            return

        # First run with no leads.json — migrate any existing CSV log once.
        self._migrate_from_csv()

    def _migrate_from_csv(self) -> None:
        """One-time import of previously logged leads from leads.csv."""
        rows = load_leads(_CSV_PATH)
        seen: set[tuple] = set()
        for row in rows:
            name_parts = (row.get("Name", "") or "").split(" ", 1)
            first = name_parts[0]
            last = name_parts[1] if len(name_parts) > 1 else ""
            domain = row.get("Domain", "")
            key = (first, last, domain)
            if key in seen or not first or not domain:
                continue
            seen.add(key)

            lead = Lead(first, last, domain)
            lead.company = row.get("Company", domain)
            lead.validated_email = row.get("Validated Email", "")
            lead.status = row.get("Verification Status", "")
            lead.subject = row.get("Email Subject", "")
            lead.pitch = row.get("Email Content", "")
            self._leads.append(lead)
            self._lead_list.addItem(QListWidgetItem(lead.display_label()))

    def closeEvent(self, event) -> None:
        """Save the working state when the window closes."""
        self._save_state()
        super().closeEvent(event)
