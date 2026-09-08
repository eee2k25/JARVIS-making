"""GUI Manipulation Interface — PyAutoGUI wrapper.

Deterministic, coordinate-based OS-level peripheral automation with the
failsafe safety net enabled. On machines without a display the module
self-reports unavailable and degrades to logged dry-run actions.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

from ..exceptions import ModuleUnavailableError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.gui")


class GuiModule(AutomationModule):
    name = "gui"

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        if sys.platform == "linux" and not (
            os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")
        ):
            return Capability(self.name, False,
                              "no X11/Wayland display (headless environment)")
        try:
            pg = self._import_pyautogui()
        except Exception as exc:  # pragma: no cover - platform specific
            return Capability(self.name, False, f"pyautogui import failed: {exc}")
        return Capability(self.name, True,
                          f"pyautogui {getattr(pg, '__version__', '?')} ready "
                          f"(FAILSAFE={pg.FAILSAFE})")

    @staticmethod
    def _import_pyautogui():
        import pyautogui  # deferred: import fails without a display

        pyautogui.FAILSAFE = True  # slam mouse to top-left corner == abort
        return pyautogui

    # ── internal ─────────────────────────────────────────────────────────
    def _pg(self):
        self.require_real()
        pg = self._import_pyautogui()
        pg.FAILSAFE = self.settings.gui_failsafe
        pg.PAUSE = self.settings.gui_pause
        return pg

    # ── cursor telemetry ─────────────────────────────────────────────────
    def position(self) -> dict[str, int]:
        """Report current cursor coordinates (safe even in dry-run)."""
        if self.dry_run:
            return {"x": 0, "y": 0, "dry_run": True}
        x, y = self._pg().position()
        return {"x": x, "y": y}

    def move_to(self, x: int, y: int, duration: float = 0.25) -> dict:
        if self.dry_run:
            return self.shadow("move_to", x=x, y=y, duration=duration)
        self._pg().moveTo(x, y, duration=duration)
        return {"moved_to": (x, y)}

    # ── click events ─────────────────────────────────────────────────────
    def click(self, x: int | None = None, y: int | None = None,
              button: str = "left", clicks: int = 1) -> dict:
        if self.dry_run:
            return self.shadow("click", x=x, y=y, button=button, clicks=clicks)
        self._pg().click(x=x, y=y, button=button, clicks=clicks,
                         interval=0.08 if clicks > 1 else 0)
        return {"clicked": (x, y), "button": button, "clicks": clicks}

    def double_click(self, x: int | None = None, y: int | None = None) -> dict:
        return self.click(x=x, y=y, clicks=2)

    def right_click(self, x: int | None = None, y: int | None = None) -> dict:
        return self.click(x=x, y=y, button="right")

    # ── keyboard execution ───────────────────────────────────────────────
    def typewrite(self, text: str, interval: float = 0.03) -> dict:
        if self.dry_run:
            return self.shadow("typewrite", text=text, interval=interval)
        self._pg().typewrite(text, interval=interval)
        return {"typed_chars": len(text)}

    def hotkey(self, *keys: str) -> dict:
        if self.dry_run:
            return self.shadow("hotkey", keys=list(keys))
        self._pg().hotkey(*keys)
        return {"hotkey": "+".join(keys)}

    def press(self, key: str, presses: int = 1) -> dict:
        if self.dry_run:
            return self.shadow("press", key=key, presses=presses)
        self._pg().press(key, presses=presses)
        return {"pressed": key, "presses": presses}

    # ── screen ───────────────────────────────────────────────────────────
    def scroll(self, amount: int) -> dict:
        if self.dry_run:
            return self.shadow("scroll", amount=amount)
        self._pg().scroll(amount)
        return {"scrolled": amount}

    def screenshot(self, path: str | None = None) -> dict:
        if self.dry_run:
            return self.shadow("screenshot", path=path)
        shot: Any = self._pg().screenshot(path)  # type: ignore[assignment]
        return {"screenshot": str(shot if path else "PIL.Image")}

    def locate_on_screen(self, image_path: str, confidence: float = 0.85) -> dict:
        if self.dry_run:
            return self.shadow("locate_on_screen", image=image_path,
                               confidence=confidence)
        box = self._pg().locateOnScreen(image_path, confidence=confidence)
        if box is None:
            return {"found": False}
        return {"found": True, "left": box.left, "top": box.top,
                "width": box.width, "height": box.height}

    def size(self) -> dict:
        if self.dry_run:
            return {"width": 0, "height": 0, "dry_run": True}
        w, h = self._pg().size()
        return {"width": w, "height": h}

    def sleep_guard(self, seconds: float) -> None:
        """Humanized pause between destructive actions (failsafe window)."""
        time.sleep(min(seconds, 5.0))
