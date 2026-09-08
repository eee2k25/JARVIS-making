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
    {"tool": "gui|browser|parser|system", "action": "<verb>", "args": {...}, "reason": "why"}
  ]
}
Allowed actions:
  gui:     move, click, double_click, right_click, type, hotkey, press, scroll, screenshot, locate
  browser: open, click, type, submit, scroll, wait, js, screenshot, save_cookies, load_cookies
  parser:  get, extract
  system:  report, sleep
Rules:
 - If the mission is informational, plan system.report with your findings in args.summary.
 - Prefer browser/parser over gui whenever a URL is involved.
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


def build_brain(settings: Settings) -> CognitiveEngine:
    """Prefer the real LLM; fall back to heuristics when unconfigured."""
    if settings.llm_api_key:
        log.info("cognitive core: LLMBrain (%s @ %s)",
                 settings.llm_model, settings.llm_base_url)
        return LLMBrain(settings)
    log.warning("no JARVIS_LLM_API_KEY set — using OfflineBrain heuristics")
    return OfflineBrain()
