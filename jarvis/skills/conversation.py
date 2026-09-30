"""ConverseSkill — the talk-to-it channel (steps 4, 5, 6 and 8 of the map).

One utterance = one full mission:
  perceive  — the operator's utterance (plus agent-injected identity + memory)
  reason    — the brain composes a reply (LLM or offline heuristic)
  act       — system.report delivers the reply; voice.speak speaks it
  verify    — a reply was produced

Run it in a loop via `python main.py chat` for an interactive session; the
mission memory keeps growing across utterances and across sessions.
"""

from __future__ import annotations

from ..exceptions import PerceptionError
from ..logging_setup import get_logger
from .base import PerceptionReport, Skill, SkillContext

log = get_logger("jarvis.skill.converse")


class ConverseSkill(Skill):
    name = "converse"
    mission = ("Converse with the operator: answer their utterance helpfully, "
               "consistent with their profile and past missions.")

    def perceive(self, ctx: SkillContext) -> PerceptionReport:
        utterance = str(ctx.params.get("utterance", "")).strip()
        if not utterance:
            raise PerceptionError("empty utterance — nothing to converse about")
        stats = {
            "chars": len(utterance),
            "words": len(utterance.split()),
        }
        ctx.memory["utterance"] = utterance
        log.info("utterance received: %s", utterance[:80])
        return PerceptionReport(
            source="chat", url="chat://operator",
            data={"utterance": utterance, "stats": stats},
        )

    def verify(self, ctx: SkillContext, act_results: list[dict]) -> tuple[bool, str]:
        reply = next((r.get("reported") for r in act_results
                      if r.get("reported")), None)
        if not reply:
            return False, "no reply produced (planned no system.report)"
        spoken = [r for r in act_results if r.get("spoken")
                  or (r.get("dry_run") and r.get("action") == "speak")]
        note = f"{reply}"
        if spoken:
            note += "  [spoken]" if not spoken[0].get("dry_run") else "  [voice shadow]"
        return True, note
