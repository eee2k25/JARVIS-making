"""LLM client + action-plan schema for the cognitive pipeline."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import requests

from ..config import Settings
from ..exceptions import ReasoningError
from ..logging_setup import get_logger

log = get_logger("jarvis.brain")

# The only tools/actions the executor will honor (defense against hallucination).
ACTION_REGISTRY: dict[str, set[str]] = {
    "gui": {"move", "click", "double_click", "right_click", "type", "hotkey",
            "press", "scroll", "screenshot", "locate"},
    "browser": {"open", "click", "type", "submit", "scroll", "wait",
                "js", "screenshot", "save_cookies", "load_cookies"},
    "parser": {"get", "extract"},
    "word": {"create", "open", "read", "add_heading", "add_text", "add_table",
             "replace", "save", "export_pdf", "launch"},
    "excel": {"create", "open", "read", "write", "append_rows", "set_formula",
              "format", "add_chart", "save", "export_pdf", "launch"},
    "powerpoint": {"create", "open", "read", "add_slide", "add_image", "save",
                   "export_pdf", "launch"},
    "system": {"report", "sleep"},
}


@dataclass(frozen=True)
class Action:
    """One automation trigger, tool-agnostic and JSON-serializable."""
    tool: str
    action: str
    args: dict = field(default_factory=dict)
    reason: str = ""

    def validate(self) -> None:
        if self.tool not in ACTION_REGISTRY:
            raise ReasoningError(f"unknown tool {self.tool!r}")
        if self.action not in ACTION_REGISTRY[self.tool]:
            raise ReasoningError(
                f"unknown action {self.tool}.{self.action} "
                f"(allowed: {sorted(ACTION_REGISTRY[self.tool])})"
            )


@dataclass
class Plan:
    """The brain's decision: rationale + ordered actions + human summary."""
    rationale: str
    summary: str
    actions: list[Action] = field(default_factory=list)
    brain: str = "unknown"


class CognitiveEngine(ABC):
    """Anything that turns perception + mission into an executable Plan."""

    @abstractmethod
    def decide(self, perception: dict, mission: str) -> Plan: ...


SYSTEM_PROMPT = """You are J.A.R.V.I.S., the decision core of a desktop/web automation agent.
You receive a mission and structured perception data (scraped page inventory).
Respond with STRICT JSON only — no markdown fences, no prose:
{
  "rationale": "why this plan",
  "summary": "one-sentence brief for the human",
  "actions": [
    {"tool": "gui|browser|parser|word|excel|powerpoint|system", "action": "<verb>", "args": {...}, "reason": "why"}
  ]
}
Allowed actions:
  gui:        move, click, double_click, right_click, type, hotkey, press, scroll, screenshot, locate
  browser:    open, click, type, submit, scroll, wait, js, screenshot, save_cookies, load_cookies
  parser:     get, extract
  word:       create, open, read, add_heading, add_text, add_table, replace, save, export_pdf, launch
  excel:      create, open, read, write, append_rows, set_formula, format, add_chart, save, export_pdf, launch
  powerpoint: create, open, read, add_slide, add_image, save, export_pdf, launch
  system:     report, sleep
Rules:
 - If the mission is informational, plan system.report with your findings in args.summary.
 - Prefer browser/parser over gui whenever a URL is involved.
 - For .docx / .pptx / .xlsx targets use the word / powerpoint / excel tools on the
   perception 'target' path (create/open first, then edit verbs, then save).
 - word/excel/powerpoint export_pdf and launch drive the real MS Office apps via COM:
   only plan them when the mission needs the desktop app; they dry-run elsewhere.
 - Keep plans minimal (<= 6 actions), deterministic and reversible.
 - If perception already answers the mission, return zero actions and say so in summary.
"""


class LLMBrain(CognitiveEngine):
    """REST client for OpenAI-compatible chat completions."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.name = f"llm:{settings.llm_model}"

    # ── REST plumbing ────────────────────────────────────────────────────
    def _chat(self, messages: list[dict]) -> str:
        url = self.settings.llm_base_url.rstrip("/") + "/chat/completions"
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.settings.llm_model,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 800,
            },
            timeout=self.settings.llm_timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    # ── JSON hardening ───────────────────────────────────────────────────
    @staticmethod
    def _extract_json(raw: str) -> dict:
        text = raw.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
        if fence:
            text = fence.group(1)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ReasoningError(f"LLM returned non-JSON output: {raw[:200]}") from exc

    # ── decision ─────────────────────────────────────────────────────────
    def decide(self, perception: dict, mission: str) -> Plan:
        user_msg = (
            f"MISSION: {mission}\n\n"
            f"PERCEPTION (json): {json.dumps(perception, default=str)[:6000]}\n\n"
            "Produce the JSON plan now."
        )
        try:
            raw = self._chat([
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ])
            data = self._extract_json(raw)
        except (requests.RequestException, KeyError) as exc:
            raise ReasoningError(f"LLM endpoint failure: {exc}") from exc

        actions: list[Action] = []
        for a in data.get("actions", [])[:8]:
            action = Action(
                tool=str(a.get("tool", "")), action=str(a.get("action", "")),
                args=dict(a.get("args", {})), reason=str(a.get("reason", "")),
            )
            action.validate()  # raises ReasoningError on hallucinated verbs
            actions.append(action)
        return Plan(
            rationale=str(data.get("rationale", "")),
            summary=str(data.get("summary", "")),
            actions=actions,
            brain=self.name,
        )


class OfflineBrain(CognitiveEngine):
    """Deterministic heuristic fallback so the loop always completes."""

    name = "offline-heuristic"

    def decide(self, perception: dict, mission: str) -> Plan:
        source = perception.get("source", "")
        if source in ("word", "excel", "powerpoint"):
            return self._office_plan(source, perception, mission)

        actions: list[Action] = []
        stats = perception.get("stats", {})
        summary_bits = [f"{k}={v}" for k, v in stats.items()]
        url = perception.get("url", "")

        actions.append(Action(
            tool="system", action="report",
            args={"summary": f"{mission} | inventory: {', '.join(summary_bits) or 'empty'}"},
            reason="compile scraped inventory into a human-readable brief",
        ))

        if url:
            actions.append(Action(
                tool="browser", action="open", args={"url": url},
                reason="render the page for dynamic verification",
            ))
            actions.append(Action(
                tool="browser", action="screenshot",
                args={"path": "logs/recon_evidence.png"},
                reason="capture visual evidence of the page state",
            ))

        if perception.get("forms"):
            actions.append(Action(
                tool="parser", action="extract",
                args={"selectors": {"form_fields": "form [name]"}},
                reason="page exposes forms — inventory their fields for future fill/submit",
            ))

        return Plan(
            rationale=(
                "Offline heuristic: no LLM endpoint configured. Planning is "
                "reduced to inventory report + evidence capture."
            ),
            summary="offline plan: report inventory, render + screenshot target",
            actions=actions,
            brain=self.name,
        )

    # ── office heuristics (Word / PowerPoint / Excel) ────────────────────
    def _office_plan(self, source: str, perception: dict, mission: str) -> Plan:
        """Report the document inventory and realize the skill's blueprint."""
        target = str(perception.get("target") or perception.get("url") or "")
        blueprint = perception.get("blueprint") or {}
        stats = perception.get("stats") or {}
        exists = (perception.get("inventory") or {}).get("exists", False)
        summary_bits = [f"{k}={v}" for k, v in stats.items()]

        actions: list[Action] = [Action(
            tool="system", action="report",
            args={"summary": f"{mission} | {source} inventory: "
                             f"{', '.join(summary_bits) or 'empty'}"},
            reason="compile the document inventory into a human-readable brief",
        )]
        if blueprint:
            actions.extend(self._realize_blueprint(source, target, blueprint,
                                                   exists))
        elif target:
            actions.append(Action(
                tool=source, action="open", args={"path": target},
                reason="load the document for inspection",
            ))
            actions.append(Action(
                tool=source, action="read", args={},
                reason="re-read the structure as act-phase evidence",
            ))

        return Plan(
            rationale=(
                "Offline heuristic: office blueprint realized with "
                f"deterministic {source} actions (no LLM endpoint configured)."
            ),
            summary=f"offline plan: {len(actions)} {source}/system action(s) "
                    f"for {target or '(unnamed document)'}",
            actions=actions,
            brain=self.name,
        )

    @staticmethod
    def _realize_blueprint(source: str, target: str, blueprint: dict,
                           exists: bool) -> list[Action]:
        """Translate a skill blueprint into ordered office edit actions.

        Word/PowerPoint blueprints append to existing documents (open) and
        generate missing ones (create). Excel blueprints describe the whole
        sheet, so the workbook is rebuilt (create) to avoid stale rows.
        """
        acts: list[Action] = []

        if source == "word":
            verb = "open" if exists else "create"
            args = {"path": target} if exists else {"path": target,
                                                   "title": blueprint.get("title")}
            acts.append(Action("word", verb, args,
                               reason="prepare the report document"))
            if blueprint.get("title"):
                acts.append(Action("word", "add_heading",
                                   {"text": blueprint["title"], "level": 1},
                                   reason="render the report title"))
            for para in blueprint.get("paragraphs", []):
                acts.append(Action("word", "add_text", {"text": para},
                                   reason="write report body text"))
            if blueprint.get("table"):
                acts.append(Action("word", "add_table",
                                   {"rows": blueprint["table"]},
                                   reason="attach the summary table"))
            acts.append(Action("word", "save", {"path": target},
                               reason="persist the document to disk"))

        elif source == "powerpoint":
            verb = "open" if exists else "create"
            args = {"path": target} if exists else {"path": target,
                                                   "title": blueprint.get("title")}
            acts.append(Action("powerpoint", verb, args,
                               reason="prepare the briefing deck"))
            for slide in blueprint.get("slides", []):
                acts.append(Action("powerpoint", "add_slide", {
                    "title": slide.get("title", ""),
                    "bullets": slide.get("bullets", []),
                    "notes": slide.get("notes"),
                }, reason="add a briefing slide"))
            acts.append(Action("powerpoint", "save", {"path": target},
                               reason="persist the deck to disk"))

        elif source == "excel":
            acts.append(Action("excel", "create", {
                "path": target,
                "title": blueprint.get("title"),
                "sheet": blueprint.get("sheet"),
            }, reason="rebuild the workbook from the blueprint"))
            block = ([blueprint["headers"]] if blueprint.get("headers") else [])
            block = block + list(blueprint.get("rows") or [])
            if block:
                acts.append(Action("excel", "write",
                                   {"start": "A1", "rows": block},
                                   reason="lay down the data grid"))
            for cell, formula in (blueprint.get("formulas") or {}).items():
                acts.append(Action("excel", "set_formula",
                                   {"cell": cell, "formula": formula},
                                   reason=f"compute {cell}"))
            if blueprint.get("format"):
                acts.append(Action("excel", "format", blueprint["format"],
                                   reason="apply spreadsheet formatting"))
            if blueprint.get("chart"):
                acts.append(Action("excel", "add_chart", blueprint["chart"],
                                   reason="attach a chart"))
            acts.append(Action("excel", "save", {"path": target},
                               reason="persist the workbook to disk"))

        return acts


def build_brain(settings: Settings) -> CognitiveEngine:
    """Prefer the real LLM; fall back to heuristics when unconfigured."""
    if settings.llm_api_key:
        log.info("cognitive core: LLMBrain (%s @ %s)",
                 settings.llm_model, settings.llm_base_url)
        return LLMBrain(settings)
    log.warning("no JARVIS_LLM_API_KEY set — using OfflineBrain heuristics")
    return OfflineBrain()
