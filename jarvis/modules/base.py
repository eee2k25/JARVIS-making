"""AutomationModule base class with capability detection + dry-run shadowing.

Every module can answer "can I actually run HERE?" — so the agent stays
importable and fully state-machine-functional on headless CI boxes while
unlocking real hardware automation on a desktop.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from ..config import Settings
from ..logging_setup import get_logger

log = get_logger("jarvis.module")


@dataclass(frozen=True)
class Capability:
    name: str
    available: bool
    detail: str

    def __str__(self) -> str:  # pragma: no cover
        mark = "✓" if self.available else "✗"
        return f"[{mark}] {self.name}: {self.detail}"


class AutomationModule(ABC):
    """Contract shared by the GUI, parser, and browser engines."""

    name: str = "module"

    def __init__(self, settings: Settings, dry_run_override: bool | None = None) -> None:
        self.settings = settings
        self._capability: Capability | None = None
        # dry_run_override=True  -> force shadow mode
        # dry_run_override=False -> demand real hardware (errors if absent)
        # None                   -> auto: shadow mode iff capability missing
        self._dry_run_override = dry_run_override
        self._last_soup = None  # most recent parse, for parser.extract follow-ups

    # ── contract ─────────────────────────────────────────────────────────
    @abstractmethod
    def check_capability(self) -> Capability:
        """Probe the environment WITHOUT importing/raising on absence."""

    # ── shared helpers ───────────────────────────────────────────────────
    @property
    def capability(self) -> Capability:
        if self._capability is None:
            self._capability = self.check_capability()
        return self._capability

    @property
    def dry_run(self) -> bool:
        if self._dry_run_override is True:
            return True
        if self._dry_run_override is False:
            return False
        return not self.capability.available

    def require_real(self) -> None:
        """Raise if a real (non-shadow) execution is impossible."""
        if self.dry_run:
            from ..exceptions import ModuleUnavailableError

            raise ModuleUnavailableError(
                f"{self.name} module is in dry-run mode: {self.capability.detail}"
            )

    def shadow(self, action: str, **args) -> dict:
        """Log a would-be action and return a synthetic dry-run result."""
        log.info("DRY-RUN %s.%s(%s)", self.name, action,
                 ", ".join(f"{k}={v!r}" for k, v in args.items()))
        return {"dry_run": True, "action": action, "args": args}
