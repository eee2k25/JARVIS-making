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


class PowerPointSkill(_OfficeSkill):
    """PowerPoint briefing mission: inventory a .pptx, then realize slide blueprints.

    Blueprints are additive for existing decks (open + append slides) and
    generative for missing ones (create + build + save):
        {"slides": [{"title": "Intro", "bullets": ["a", "b"], "notes": "..."}]}
    """

    name = "powerpoint"
    engine = "powerpoint"
    mission = ("MS PowerPoint mission: maintain the briefing deck "
               "per the blueprint.")

    def _empty_inventory(self) -> dict:
        return {"slide_count": 0, "slides": []}

    def _stats(self, inventory: dict) -> dict:
        slides = inventory.get("slides", [])
        return {
            "exists": inventory.get("exists", False),
            "slides": inventory.get("slide_count", len(slides)),
            "bullets": sum(len(s.get("bullets", [])) for s in slides),
            "with_notes": sum(1 for s in slides if s.get("notes")),
        }

    def _verify_content(self, ctx, target, blueprint, stats):
        module = ctx.agent.modules[self.engine]
        module.open(str(target))
        inv = module.read()
        if inv.get("dry_run"):
            return True, "deck content verified in shadow mode"

        want = len(blueprint.get("slides") or [])
        have = inv.get("slide_count", 0)
        if have < want:
            return False, f"expected >= {want} slide(s), found {have}"
        titles = [s.get("title", "") for s in inv.get("slides", [])]
        expected_titles = [s.get("title", "") for s in blueprint["slides"]
                           if s.get("title")]
        missing = [t for t in expected_titles if t not in titles]
        if missing:
            return False, f"slide title(s) missing: {missing}"
        bullets = sum(len(s.get("bullets", [])) for s in inv.get("slides", []))
        return True, (f"deck OK (slides={have}, bullets={bullets}, "
                      f"titles verified={len(expected_titles)})")


class ExcelSkill(_OfficeSkill):
    """Excel workbook mission: inventory a .xlsx, then realize the grid blueprint.

    Unlike Word/PowerPoint, an Excel blueprint describes the WHOLE sheet, so
    the workbook is rebuilt on every realization (no stale rows):
        {"title": "Budget", "sheet": "Q3",
         "headers": ["Item", "Qty"], "rows": [["A", 2]],
         "formulas": {"C2": "=B2*10"}, "format": {"target": "A1:B1", "bold": true}}
    """

    name = "excel"
    engine = "excel"
    mission = "MS Excel mission: maintain the workbook per the blueprint."

    def _empty_inventory(self) -> dict:
        return {"sheets": [], "rows": [], "formulas": {}, "max_row": 0}

    def _stats(self, inventory: dict) -> dict:
        rows = [r for r in inventory.get("rows", [])
                if any(c is not None for c in r)]
        return {
            "exists": inventory.get("exists", False),
            "sheets": len(inventory.get("sheets", [])),
            "rows": len(rows),
            "formulas": len(inventory.get("formulas", {})),
        }

    def _verify_content(self, ctx, target, blueprint, stats):
        module = ctx.agent.modules[self.engine]
        module.open(str(target))
        inv = module.read(sheet=blueprint.get("sheet"))
        if inv.get("dry_run"):
            return True, "workbook content verified in shadow mode"

        rows = [r for r in inv.get("rows", [])
                if any(c is not None for c in r)]
        expected = ((1 if blueprint.get("headers") else 0)
                    + len(blueprint.get("rows") or []))
        if len(rows) != expected:
            return False, (f"expected {expected} populated row(s), "
                           f"found {len(rows)}")
        formulas = inv.get("formulas", {})
        for cell in (blueprint.get("formulas") or {}):
            if cell not in formulas:
                return False, f"formula missing at cell {cell}"
        return True, (f"workbook OK (sheets={len(inv.get('sheets', []))}, "
                      f"rows={len(rows)}, formulas={len(formulas)})")
