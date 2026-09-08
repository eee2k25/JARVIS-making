"""WebReconSkill — reference implementation of a full agent cycle.

Perceive:  fetch a URL with the parser engine and compile a page inventory
           (title, headings, links, tables, forms, text stats).
Reason:    the brain turns the inventory into an action plan.
Act:       executor runs the plan (report, browser render, screenshot...).
Verify:    confirm artifacts exist and inventory is non-empty.
"""

from __future__ import annotations

from ..exceptions import PerceptionError
from ..logging_setup import get_logger
from .base import PerceptionReport, Skill, SkillContext

log = get_logger("jarvis.skill.recon")


class WebReconSkill(Skill):
    name = "web_recon"
    mission = "Reconnaissance: inventory the target page and capture evidence."

    def __init__(self, url: str, selectors: dict[str, str] | None = None) -> None:
        self.url = url
        self.selectors = selectors or {}

    # ── PERCEIVE ─────────────────────────────────────────────────────────
    def perceive(self, ctx: SkillContext) -> PerceptionReport:
        parser = ctx.agent.modules["parser"]
        result = parser.get(self.url)
        if not result.ok:
            raise PerceptionError(f"target returned HTTP {result.status_code}")

        soup = result.soup
        inventory = {
            "title": parser.title(soup),
            "headings": parser.headings(soup),
            "links": parser.find_links(soup, base_url=self.url),
            "tables": parser.find_tables(soup),
            "forms": parser.find_forms(soup),
        }
        if self.selectors:
            inventory["custom"] = parser.extract(soup, self.selectors)

        stats = {
            "status": result.status_code,
            "elapsed_ms": round(result.elapsed_ms),
            "headings": len(inventory["headings"]),
            "links": len(inventory["links"]),
            "tables": len(inventory["tables"]),
            "forms": len(inventory["forms"]),
            "text_chars": len(result.text),
        }
        log.info("inventory compiled: %s", stats)
        ctx.memory["inventory"] = inventory
        ctx.memory["stats"] = stats

        return PerceptionReport(source="parser", url=result.url,
                                data={**inventory, "stats": stats})

    # ── VERIFY ───────────────────────────────────────────────────────────
    def verify(self, ctx: SkillContext, act_results: list[dict]) -> tuple[bool, str]:
        stats = ctx.memory.get("stats", {})
        if not stats:
            return False, "no perception artifacts recorded"

        if stats.get("text_chars", 0) < 20:
            return False, "page inventory suspiciously small (<20 chars)"

        evidence = [r for r in act_results if r.get("screenshot")]
        if evidence and all(r.get("dry_run") for r in evidence):
            log.info("evidence captured in dry-run shadow mode (no display here)")
        return True, (
            f"inventory OK (links={stats.get('links')}, tables={stats.get('tables')}, "
            f"forms={stats.get('forms')}, text={stats.get('text_chars')} chars)"
        )
