"""DailyBriefSkill — the connected-tools morning brief (steps 5, 7 and 8).

Perceive:  pull upcoming calendar events + recent inbox + mission memory.
Reason:    the brain composes the brief (LLM or offline heuristic).
Act:       system.report delivers it; voice.speak reads it aloud; channels
           (telegram/slack) can fan it out when configured.
Verify:    a brief was produced.

Everything shadows cleanly when email/calendar/voice are unconfigured, so
the full cycle runs anywhere and lights up as each credential lands.
"""

from __future__ import annotations

from ..logging_setup import get_logger
from .base import PerceptionReport, Skill, SkillContext

log = get_logger("jarvis.skill.briefing")


class DailyBriefSkill(Skill):
    name = "daily_brief"
    mission = ("Compile the operator's daily brief: upcoming calendar, "
               "recent inbox, and what the agent remembers.")

    def __init__(self, days: int = 7, inbox_limit: int = 5) -> None:
        self.days = days
        self.inbox_limit = inbox_limit

    def perceive(self, ctx: SkillContext) -> PerceptionReport:
        agent = ctx.agent

        cal_res = agent.modules["calendar"].upcoming(self.days)
        if cal_res.get("dry_run"):
            events, cal_note = [], "calendar unconfigured (shadow)"
        else:
            events, cal_note = cal_res.get("events", []), "live"

        mail_res = agent.modules["email"].inbox(self.inbox_limit)
        if mail_res.get("dry_run"):
            messages, mail_note = [], "email unconfigured (shadow)"
        else:
            messages, mail_note = mail_res.get("messages", []), "live"

        stats = {
            "calendar_events": len(events),
            "emails": len(messages),
            "memories": agent.memory.count(),
            "calendar": cal_note,
            "email": mail_note,
        }
        log.info("briefing perceived: %s", stats)
        ctx.memory["stats"] = stats
        return PerceptionReport(
            source="briefing", url="briefing://daily",
            data={"calendar": events, "inbox": messages, "stats": stats},
        )

    def verify(self, ctx: SkillContext, act_results: list[dict]) -> tuple[bool, str]:
        brief = next((r.get("reported") for r in act_results
                      if r.get("reported")), None)
        if not brief:
            return False, "no brief produced (planned no system.report)"
        stats = ctx.memory.get("stats", {})
        return True, (f"brief delivered (events={stats.get('calendar_events', 0)}, "
                      f"emails={stats.get('emails', 0)}, "
                      f"memories={stats.get('memories', 0)})")
