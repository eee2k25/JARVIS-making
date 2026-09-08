"""JARVIS orchestrator — boots modules, drives the state machine, executes skills.

Lifecycle per skill run:
    IDLE -> PERCEIVING -> REASONING -> ACTING -> VERIFYING -> IDLE
                       \\-> ERROR -> RECOVERING -> (retry | give up)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .cognition.llm import Action, CognitiveEngine, build_brain
from .config import Settings
from .exceptions import (ActionError, JarvisError, ReasoningError,
                         SkillNotFoundError)
from .logging_setup import get_logger, setup_logging
from .modules.base import AutomationModule
from .modules.browser import BrowserModule
from .modules.gui import GuiModule
from .modules.parser import ParserModule
from .skills.base import Skill, SkillContext
from .state_machine import AgentState as S
from .state_machine import StateMachine

log = get_logger("jarvis.agent")


@dataclass
class SkillResult:
    success: bool
    skill: str
    attempts: int
    summary: str
    rationale: str = ""
    brain: str = ""
    actions_executed: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    state_trace: list[str] = field(default_factory=list)


class ActionExecutor:
    """Whitelisted translation of Action plans into module calls.

    Every dispatch is explicit — no getattr on user/LLM-controlled strings.
    """

    def __init__(self, modules: dict[str, AutomationModule]) -> None:
        self.modules = modules

    def execute(self, action: Action) -> dict:
        action.validate()
        if action.tool == "system":
            return self._system(action)
        module = self.modules.get(action.tool)
        if module is None:
            raise ActionError(f"module {action.tool} not loaded")

        dispatch: dict[tuple[str, str], Any] = {
            # gui
            ("gui", "move"): lambda a: module.move_to(**a),
            ("gui", "click"): lambda a: module.click(**a),
            ("gui", "double_click"): lambda a: module.double_click(**a),
            ("gui", "right_click"): lambda a: module.right_click(**a),
            ("gui", "type"): lambda a: module.typewrite(a.get("text", "")),
            ("gui", "hotkey"): lambda a: module.hotkey(*a.get("keys", [])),
            ("gui", "press"): lambda a: module.press(a.get("key", "enter"),
                                                    a.get("presses", 1)),
            ("gui", "scroll"): lambda a: module.scroll(a.get("amount", -600)),
            ("gui", "screenshot"): lambda a: module.screenshot(a.get("path")),
            ("gui", "locate"): lambda a: module.locate_on_screen(a["image"]),
            # browser
            ("browser", "open"): lambda a: module.open(a["url"]),
            ("browser", "click"): lambda a: module.click(a["selector"]),
            ("browser", "type"): lambda a: module.type(a["selector"], a.get("text", "")),
            ("browser", "submit"): lambda a: module.submit(a.get("selector", "form")),
            ("browser", "scroll"): lambda a: module.scroll(a.get("pixels", 800)),
            ("browser", "wait"): lambda a: module.wait_for(a["selector"],
                                                           a.get("timeout", 10)),
            ("browser", "js"): lambda a: module.execute_js(a["script"]),
            ("browser", "screenshot"): lambda a: module.screenshot(a.get("path")),
            ("browser", "save_cookies"): lambda a: module.save_cookies(a.get("path",
                                                                             "logs/cookies.json")),
            ("browser", "load_cookies"): lambda a: module.load_cookies(a.get("path",
                                                                             "logs/cookies.json")),
            # parser
            ("parser", "get"): lambda a: self._parse_get(module, a),
            ("parser", "extract"): lambda a: self._parse_extract(module, a),
        }
        key = (action.tool, action.action)
        if key not in dispatch:
            raise ActionError(f"no executor bound for {action.tool}.{action.action}")

        log.info("ACT %s.%s %s", action.tool, action.action,
                 f"({action.reason})" if action.reason else "")
        result = dispatch[key](action.args)
        result["dry_run"] = bool(result.get("dry_run", False))
        return result

    # ── built-in system tool ─────────────────────────────────────────────
    @staticmethod
    def _system(action: Action) -> dict:
        if action.action == "report":
            summary = action.args.get("summary", "(empty report)")
            log.info("REPORT: %s", summary)
            return {"reported": summary}
        if action.action == "sleep":
            seconds = min(float(action.args.get("seconds", 1)), 10)
            time.sleep(seconds)
            return {"slept": seconds}
        raise ActionError(f"unknown system action {action.action}")

    # ── parser follow-ups (results recorded into run memory) ─────────────
    @staticmethod
    def _parse_get(module: ParserModule, args: dict) -> dict:
        res = module.get(args["url"])
        return {"status": res.status_code, "url": res.url,
                "text_chars": len(res.text)}

    @staticmethod
    def _parse_extract(module: ParserModule, args: dict) -> dict:
        # uses the most recent fetch cached on the module by _parse_get
        soup = getattr(module, "_last_soup", None)
        if soup is None:
            raise ActionError("parser.extract requires a prior parser.get")
        return {"extracted": module.extract(soup, args.get("selectors", {}))}


class JarvisAgent:
    """Top-level supervisor: owns modules, brain, and the state machine."""

    def __init__(self, settings: Settings | None = None,
                 dry_run: bool | None = None) -> None:
        self.settings = settings or Settings.load()
        setup_logging(self.settings.log_level, self.settings.log_file or None)
        self.sm = StateMachine()
        self.sm.add_listener(self._trace_listener)
        self.trace: list[str] = []

        mode = True if dry_run else (None if dry_run is None else False)
        self.modules: dict[str, AutomationModule] = {
            "gui": GuiModule(self.settings, dry_run_override=mode),
            "parser": ParserModule(self.settings, dry_run_override=mode),
            "browser": BrowserModule(self.settings, dry_run_override=mode),
        }
        self.brain: CognitiveEngine = build_brain(self.settings)
        self.executor = ActionExecutor(self.modules)
        self.skills: dict[str, Skill] = {}
        self._last_soup: Any = None

    # ── state tracing ────────────────────────────────────────────────────
    def _trace_listener(self, t) -> None:
        stamp = time.strftime("%H:%M:%S", time.localtime(t.ts))
        self.trace.append(f"{stamp}  {t.frm.value:>12} -> {t.to.value:<12} {t.note}")

    # ── lifecycle ────────────────────────────────────────────────────────
    def boot(self) -> "JarvisAgent":
        run_id = self.sm.new_run()
        log.info("J.A.R.V.I.S. boot sequence starting (run=%s)", run_id)
        self.sm.transition(S.BOOTING, note="initializing modules")

        for name, module in self.modules.items():
            cap = module.capability
            log.info("module %-8s %s", name,
                     "READY " + cap.detail if cap.available
                     else "SHADOW " + cap.detail)

        self.sm.transition(S.IDLE, note="all modules probed")
        log.info("boot complete — agent %s",
                 "IDLE and ready" if True else "")
        return self

    def register(self, skill: Skill) -> "JarvisAgent":
        self.skills[skill.name] = skill
        log.info("skill registered: %s", skill.name)
        return self

    def shutdown(self, reason: str = "operator request") -> None:
        if self.sm.terminal:
            return
        # Bridge to a state that may legally enter SHUTTING_DOWN, even if we
        # are mid-cycle (e.g. an exception fired while ACTING).
        if not self.sm.can(S.SHUTTING_DOWN):
            bridge = S.BOOTING if self.sm.state is S.OFF else S.ERROR
            self.sm.transition(bridge, note="forced bridge for shutdown")
        self.sm.transition(S.SHUTTING_DOWN, note=reason)
        self.modules["browser"].quit()
        self.sm.transition(S.TERMINATED, note="session complete")
        log.info("J.A.R.V.I.S. terminated")

    def __enter__(self) -> "JarvisAgent":
        return self.boot()

    def __exit__(self, exc_type, exc, tb) -> None:
        self.shutdown(reason="context exit" if exc_type is None
                      else f"exception: {exc_type.__name__}")

    # ── mission execution ────────────────────────────────────────────────
    def run(self, skill: Skill | str, **params: Any) -> SkillResult:
        if isinstance(skill, str):
            if skill not in self.skills:
                raise SkillNotFoundError(
                    f"skill {skill!r} not registered "
                    f"(have: {sorted(self.skills)})")
            skill = self.skills[skill]

        if self.sm.state is not S.IDLE:
            raise JarvisError(
                f"agent not IDLE (state={self.sm.state.value}); cannot run skill")

        run_id = self.sm.new_run()
        started = time.monotonic()
        result = SkillResult(success=False, skill=skill.name, attempts=0,
                             summary="", state_trace=[])

        for module in self.modules.values():  # hook parser cache
            if hasattr(module, "_last_soup"):
                module._last_soup = None

        attempt = 0
        while True:
            result.attempts = attempt + 1
            try:
                # 1 ── PERCEIVE ───────────────────────────────────────
                ctx = SkillContext(agent=self, mission=skill.mission,
                                   params=params)
                self.sm.transition(S.PERCEIVING, note=f"{skill.name} (attempt {attempt + 1})")
                perception = skill.perceive(ctx)

                # 2 ── REASON ─────────────────────────────────────────
                self.sm.transition(S.REASONING, note=f"brain={self.brain.name}")
                plan = self.brain.decide(perception.to_dict(), skill.mission)
                log.info("plan (%d actions): %s", len(plan.actions), plan.summary)
                result.rationale, result.brain = plan.rationale, plan.brain

                # 3 ── ACT ────────────────────────────────────────────
                self.sm.transition(S.ACTING,
                                   note=f"executing {len(plan.actions)} action(s)")
                act_results: list[dict] = []
                for action in plan.actions:
                    act_results.append(self.executor.execute(action))
                result.actions_executed = [
                    {"tool": a.tool, "action": a.action, **{k: v for k, v in r.items()}}
                    for a, r in zip(plan.actions, act_results)
                ]

                # 4 ── VERIFY ─────────────────────────────────────────
                self.sm.transition(S.VERIFYING, note="post-conditions")
                ok, note = skill.verify(ctx, act_results)
                if ok:
                    self.sm.transition(S.IDLE, note="mission accomplished")
                    result.success = True
                    result.summary = note
                    break
                raise JarvisError(f"verification failed: {note}")

            except JarvisError as exc:
                result.errors.append(f"attempt {attempt + 1}: {exc}")
                log.error("run failure: %s", exc)
                self.sm.transition(S.ERROR, note=str(exc)[:120])

                if attempt >= self.settings.max_retries:
                    self.sm.transition(S.IDLE,
                                       note="retries exhausted — returning control")
                    result.summary = f"FAILED after {attempt + 1} attempts"
                    break

                delay = self.sm.backoff(attempt, base=self.settings.backoff_base,
                                        jitter=self.settings.backoff_jitter)
                self.sm.transition(S.RECOVERING,
                                   note=f"retry in {delay:.1f}s")
                time.sleep(delay)
                attempt += 1

        result.elapsed_s = round(time.monotonic() - started, 2)
        result.state_trace = list(self.trace)
        log.info("skill %s finished: %s (%.2fs, %d attempt(s))",
                 skill.name, "SUCCESS" if result.success else "FAILURE",
                 result.elapsed_s, result.attempts)
        return result
