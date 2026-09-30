"""Shared foundation for the MS Office automation modules (Word/PowerPoint/Excel).

Each Office module runs on a two-engine design:

* file engine  — cross-platform document manipulation via the Open XML
  libraries (python-docx, python-pptx, openpyxl). Creates, reads, edits and
  saves real .docx / .pptx / .xlsx artifacts anywhere Python runs.
* app engine   — the real Microsoft desktop applications driven through the
  Windows COM bridge (pywin32: ``Word.Application``, ``PowerPoint.Application``,
  ``Excel.Application``). Where the desktop app is absent (Linux, CI, headless
  sandboxes) app-engine verbs degrade to the standard dry-run shadow log —
  and become live on a Windows rig with Office installed, zero code changes.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from ..exceptions import ActionError, ModuleUnavailableError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.office")


class OfficeModule(AutomationModule):
    """Engine plumbing shared by the Word, PowerPoint and Excel modules."""

    # overridden by each app module
    progid: str = ""            # COM ProgID, e.g. "Word.Application"
    file_module: str = ""       # importable Open XML library, e.g. "docx"
    app_label: str = "MS Office"

    def __init__(self, settings, dry_run_override: bool | None = None) -> None:
        super().__init__(settings, dry_run_override)
        self._doc = None            # in-memory document handle (app-specific)
        self._path: Path | None = None
        self._app_instance = None   # live COM application, when driving the app

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        try:
            lib = importlib.import_module(self.file_module)
        except ImportError as exc:
            return Capability(self.name, False, f"missing dependency: {exc}")
        ver = getattr(lib, "__version__", "?")
        detail = f"{self.file_module} {ver} file engine"
        if self.app_available():
            detail += f" + {self.progid} COM app engine"
        else:
            detail += f" + app-engine shadow (no {self.progid} on this machine)"
        return Capability(self.name, True, detail)

    # ── app engine (real MS Office via COM, Windows only) ────────────────
    def app_available(self) -> bool:
        """True when the real desktop app can be automated here."""
        if sys.platform != "win32":
            return False
        try:
            import win32com.client  # noqa: F401
        except ImportError:
            return False
        return True

    def _app(self):
        """Start (or reuse) the real Office application. Raises when absent."""
        self.require_real()
        if not self.app_available():
            raise ModuleUnavailableError(
                f"{self.app_label} app engine unavailable "
                f"({self.progid} needs Windows + MS Office + pywin32)"
            )
        if self._app_instance is None:
            import win32com.client

            log.info("starting %s via COM (%s)", self.app_label, self.progid)
            self._app_instance = win32com.client.Dispatch(self.progid)
        return self._app_instance

    def app_shadow(self, action: str, **args) -> dict | None:
        """Shadow result when the real app engine is unavailable, else None."""
        if self.dry_run or not self.app_available():
            return self.shadow(action, **args)
        return None

    # ── helpers ──────────────────────────────────────────────────────────
    def _target_path(self, path: str | Path | None, suffix: str | None = None) -> Path:
        """Resolve the artifact path, defaulting to the currently open file."""
        p = Path(path) if path else self._path
        if p is None:
            raise ActionError(f"{self.name}: no path given and no document open")
        if suffix and p.suffix.lower() != suffix:
            p = p.with_suffix(suffix)
        return p

    def _abs(self, path: Path) -> str:
        return str(path.expanduser().resolve())

    # ── teardown ─────────────────────────────────────────────────────────
    def close(self) -> dict:
        """Release the in-memory document handle."""
        self._doc = None
        return {"closed": True}

    def quit(self) -> None:
        """Close the document and tear down any live COM application."""
        self.close()
        if self._app_instance is not None:
            try:
                self._app_instance.Quit()
            except Exception:  # pragma: no cover - COM teardown is best effort
                pass
            self._app_instance = None
            log.info("%s app engine session closed", self.app_label)
