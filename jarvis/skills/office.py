"""MS Office skills — full perceive -> reason -> act -> verify cycles for the
Word, PowerPoint and Excel engines.

Each skill:
  perceive  — inventory the target document (structure, stats) or note its absence
  reason    — the brain (LLM or offline heuristic) turns the inventory + blueprint
              into a plan of word/powerpoint/excel actions
  act       — the executor runs the plan (create, edit, save, export...)
  verify    — re-open the artifact and confirm the blueprint's content landed
"""

from __future__ import annotations

from pathlib import Path

from ..exceptions import PerceptionError
from ..logging_setup import get_logger
from .base import PerceptionReport, Skill, SkillContext

log = get_logger("jarvis.skill.office")


class _OfficeSkill(Skill):
    """Shared lifecycle for document missions (Word / PowerPoint / Excel)."""

    engine: str = ""        # module key + action tool: word | powerpoint | excel

    def __init__(self, path: str | Path, blueprint: dict | None = None,
                 mission: str | None = None) -> None:
        self.path = Path(path)
        self.blueprint = blueprint or {}
        if mission:
            self.mission = mission

    # ── PERCEIVE ─────────────────────────────────────────────────────────
    def perceive(self, ctx: SkillContext) -> PerceptionReport:
        module = ctx.agent.modules[self.engine]
        exists = self.path.exists()
        if not exists and not self.blueprint:
            raise PerceptionError(
                f"{self.engine}: target missing and no blueprint to build from: "
                f"{self.path}")

        inventory: dict = {"path": str(self.path), "exists": exists}
        if exists:
            opened = module.open(str(self.path))
            if opened.get("dry_run"):
                inventory["dry_run"] = True
            else:
                inv = module.read()
                if inv.get("dry_run"):
                    inventory["dry_run"] = True
                else:
                    inventory.update(inv)
        else:
            inventory.update(self._empty_inventory())

        stats = self._stats(inventory)
        log.info("%s inventory: %s", self.engine, stats)
        ctx.memory.update(target=str(self.path), blueprint=self.blueprint,
                          inventory=inventory, stats=stats)
        return PerceptionReport(
            source=self.engine, url=str(self.path),
            data={"inventory": inventory, "stats": stats,
                  "target": str(self.path), "blueprint": self.blueprint},
        )

    # ── VERIFY ───────────────────────────────────────────────────────────
    def verify(self, ctx: SkillContext, act_results: list[dict]) -> tuple[bool, str]:
        target = Path(ctx.memory["target"])
        blueprint = ctx.memory.get("blueprint") or {}
        stats = ctx.memory.get("stats") or {}

        # system.report / system.sleep are not engine work
        work = [r for r in act_results
                if "reported" not in r and "slept" not in r]
        live = [r for r in work if not r.get("dry_run")]
        shadow = [r for r in work if r.get("dry_run")]

        if work and not live and shadow:
            return True, (f"verified in dry-run shadow mode "
                          f"({self.engine} engine idle on this machine)")

        if not target.exists():
            if blueprint:
                return False, f"artifact missing: {target}"
            return True, f"inventory-only OK ({self._fmt_stats(stats)})"

        if not blueprint:
            return True, f"inventory OK ({self._fmt_stats(stats)})"

        return self._verify_content(ctx, target, blueprint, stats)

    # ── per-app hooks ────────────────────────────────────────────────────
    def _empty_inventory(self) -> dict:
        """Structure of a not-yet-existing document."""
        return {}

    def _stats(self, inventory: dict) -> dict:  # pragma: no cover - per app
        return {}

    def _fmt_stats(self, stats: dict) -> str:
        return ", ".join(f"{k}={v}" for k, v in stats.items()) or "empty"

    def _verify_content(self, ctx: SkillContext, target: Path,
                        blueprint: dict, stats: dict) -> tuple[bool, str]:
        raise NotImplementedError


class WordSkill(_OfficeSkill):
    """Word report mission: inventory a .docx, then realize a content blueprint.

    Blueprints are additive for existing documents (open + append) and
    generative for missing ones (create + write + save):
        {"title": "Report", "paragraphs": ["body", ...],
         "table": [["h1", "h2"], ["c1", "c2"]]}
    """

    name = "word"
    engine = "word"
    mission = "MS Word mission: maintain the report document per the blueprint."

    def _empty_inventory(self) -> dict:
        return {"paragraphs": [], "headings": [], "tables": [], "word_count": 0}

    def _stats(self, inventory: dict) -> dict:
        return {
            "exists": inventory.get("exists", False),
            "headings": len(inventory.get("headings", [])),
            "paragraphs": len(inventory.get("paragraphs", [])),
            "tables": len(inventory.get("tables", [])),
            "word_count": inventory.get("word_count", 0),
        }

    def _verify_content(self, ctx, target, blueprint, stats):
        module = ctx.agent.modules[self.engine]
        module.open(str(target))
        inv = module.read()
        if inv.get("dry_run"):
            return True, "document content verified in shadow mode"

        headings = len(inv.get("headings", []))
        tables = len(inv.get("tables", []))
        words = inv.get("word_count", 0)
        need_headings = 1 if blueprint.get("title") else 0
        need_tables = 1 if blueprint.get("table") else 0

        if headings < need_headings:
            return False, f"expected >= {need_headings} heading(s), found {headings}"
        if tables < need_tables:
            return False, f"expected >= {need_tables} table(s), found {tables}"
        if words < 5:
            return False, f"document body too small ({words} words)"
        return True, (f"document OK (headings={headings}, tables={tables}, "
                      f"words={words})")
