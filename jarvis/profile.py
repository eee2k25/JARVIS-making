"""Operator identity — 'teach it who I am' (step 4 of the nine-step map).

The profile is a plain markdown file describing the operator: their work,
goals, preferences and boundaries. It is loaded at boot and injected into
every cognitive decision, so the brain answers *as your assistant* rather
than a generic model.

Default location: assets/profile/operator.md (override with
JARVIS_OPERATOR_PROFILE). A sensible fallback is used when the file is
absent, so the loop never breaks on a fresh checkout.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, project_root
from .logging_setup import get_logger

log = get_logger("jarvis.profile")

DEFAULT_PROFILE = """\
name: Operator
work: general automation and research
goals: keep the agent useful, safe and to the point
preferences: concise answers, concrete actions, no filler
boundaries: never touch credentials; always verify results
"""

_NAME_RE = re.compile(r"^\s*name:\s*(.+?)\s*$", re.MULTILINE)


@dataclass(frozen=True)
class OperatorProfile:
    """Who JARVIS works for and how they like things done."""

    path: Path
    text: str

    @property
    def name(self) -> str:
        match = _NAME_RE.search(self.text)
        return match.group(1) if match else "Operator"

    def as_dict(self) -> dict:
        return {"name": self.name, "path": str(self.path),
                "profile": self.text[:2000]}

    def summary(self) -> str:
        return f"{self.name} ({len(self.text)} chars from {self.path})"

    @classmethod
    def load(cls, settings: Settings | None = None) -> "OperatorProfile":
        """Load the profile file, falling back to the built-in default."""
        configured = (settings.operator_profile if settings else "") or ""
        path = (Path(configured).expanduser() if configured
                else project_root() / "assets" / "profile" / "operator.md")
        if path.exists():
            text = path.read_text(encoding="utf-8")
            log.info("operator profile loaded: %s", path)
        else:
            text = DEFAULT_PROFILE
            log.warning("operator profile %s not found — using default", path)
        return cls(path=path, text=text)
