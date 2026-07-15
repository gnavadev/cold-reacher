# workers.py

"""
QThread-based background workers.

Each worker emits signals the main window connects to — never touches widgets
directly. All heavy I/O (SMTP, API calls) stays off the GUI thread.
"""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from engines.validator import find_valid_email
from engines.ai_generator import generate_pitch


class ValidationWorker(QThread):
    # NOTE: do NOT declare a custom `finished` signal — QThread already provides
    # one that fires exactly once when run() returns. Shadowing it caused the
    # slot to run twice (manual emit + native emit).
    log_message = Signal(str)
    result_ready = Signal(object)   # ValidationResult | None

    def __init__(
        self,
        first: str,
        last: str,
        domain: str,
        reacher_url: str = "",
        hunter_key: str = "",
        zerobounce_key: str = "",
        abstract_key: str = "",
        parent=None,
    ):
        super().__init__(parent)

        self._first           = first
        self._last            = last
        self._domain          = domain
        self._reacher_url     = reacher_url
        self._hunter_key      = hunter_key
        self._zerobounce_key  = zerobounce_key
        self._abstract_key    = abstract_key

    def run(self) -> None:
        try:
            result = find_valid_email(
                self._first,
                self._last,
                self._domain,
                log=self.log_message.emit,
                reacher_url=self._reacher_url or None,
                hunter_key=self._hunter_key or None,
                zerobounce_key=self._zerobounce_key or None,
                abstract_key=self._abstract_key or None,
            )
            self.result_ready.emit(result)

        except Exception as exc:
            self.log_message.emit(f"[ERROR] Validation worker crashed: {exc}")
            self.result_ready.emit(None)


class PitchWorker(QThread):
    # NOTE: no custom `finished` signal — QThread's built-in one fires once.
    log_message = Signal(str)
    result_ready = Signal(object)   # GeneratedPitch
    error = Signal(str)

    def __init__(
        self,
        target_name: str,
        company: str,
        raw_context: str,
        api_key: str,
        sender_name: str = "",
        sender_website: str = "",
        instructions: str = "",
        parent=None,
    ):
        super().__init__(parent)

        self._target_name    = target_name
        self._company        = company
        self._raw_context    = raw_context
        self._api_key        = api_key
        self._sender_name    = sender_name
        self._sender_website = sender_website
        self._instructions   = instructions

    def run(self) -> None:
        self.log_message.emit("[INFO] Calling Gemini API...")

        try:
            pitch = generate_pitch(
                self._target_name,
                self._company,
                self._raw_context,
                api_key=self._api_key,
                sender_name=self._sender_name,
                sender_website=self._sender_website,
                instructions=self._instructions,
            )

            self.log_message.emit("[SUCCESS] Pitch generated.")
            self.result_ready.emit(pitch)

        except Exception as exc:
            self.log_message.emit(f"[ERROR] Pitch generation failed: {exc}")
            self.error.emit(str(exc))
