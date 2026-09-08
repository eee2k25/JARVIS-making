"""Skill contract: perceive + verify, with the brain handling 'reason'."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from ..agent import JarvisAgent


@dataclass
class SkillContext:
    """Everything a skill may touch during its lifecycle."""
    agent: "JarvisAgent"
    mission: str
    params: dict = field(default_factory=dict)
    # shared scratch space across the perceive -> reason -> act -> verify cycle
    memory: dict = field(default_factory=dict)


@dataclass
class PerceptionReport:
    """Structured environmental data handed to the cognitive pipeline."""
    source: str
    url: str
    data: dict[str, Any]

    def to_dict(self) -> dict:
        return {"source": self.source, "url": self.url, **self.data}


class Skill(ABC):
    """A composable mission: scrape -> decide -> act -> verify."""

    name: str = "skill"
    mission: str = "complete the objective"

    @abstractmethod
    def perceive(self, ctx: SkillContext) -> PerceptionReport:
        """Ingest environmental data (parser/browser). Must not act."""

    @abstractmethod
    def verify(self, ctx: SkillContext, act_results: list[dict]) -> tuple[bool, str]:
        """Post-condition check. Returns (ok, note)."""
