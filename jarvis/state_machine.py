"""Generic, auditable finite state machine powering the agent lifecycle.

Design goals:
  * Explicit transition table — no implicit state changes, ever.
  * Listeners on entry/exit for logging, metrics, and side-effect gating.
  * Immutable history so any run can be replayed/audited after the fact.
"""

from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, Set

from .exceptions import InvalidTransitionError
from .logging_setup import get_logger, run_id_var, state_var

log = get_logger("jarvis.sm")


class AgentState(str, Enum):
    """Execution lifecycle of the agent."""

    OFF = "OFF"                        # not yet booted
    BOOTING = "BOOTING"                # module init / capability probes
    IDLE = "IDLE"                      # healthy, awaiting mission
    PERCEIVING = "PERCEIVING"          # data ingestion (bs4 / selenium fetch)
    REASONING = "REASONING"            # LLM decision pipeline
    ACTING = "ACTING"                  # automation triggers (pyautogui/selenium)
    VERIFYING = "VERIFYING"            # post-condition checks
    ERROR = "ERROR"                    # a stage failed
    RECOVERING = "RECOVERING"          # backoff before retry
    SHUTTING_DOWN = "SHUTTING_DOWN"    # graceful teardown
    TERMINATED = "TERMINATED"          # final; no transitions out


# ── Legal transitions ────────────────────────────────────────────────────────
TRANSITIONS: Dict[AgentState, Set[AgentState]] = {
    AgentState.OFF: {AgentState.BOOTING},
    AgentState.BOOTING: {AgentState.IDLE, AgentState.ERROR, AgentState.SHUTTING_DOWN},
    AgentState.IDLE: {AgentState.PERCEIVING, AgentState.SHUTTING_DOWN},
    AgentState.PERCEIVING: {AgentState.REASONING, AgentState.ERROR},
    AgentState.REASONING: {AgentState.ACTING, AgentState.ERROR},
    AgentState.ACTING: {AgentState.VERIFYING, AgentState.ERROR},
    AgentState.VERIFYING: {AgentState.IDLE, AgentState.ERROR},
    AgentState.ERROR: {AgentState.RECOVERING, AgentState.IDLE, AgentState.SHUTTING_DOWN},
    AgentState.RECOVERING: {AgentState.PERCEIVING, AgentState.IDLE, AgentState.SHUTTING_DOWN},
    AgentState.SHUTTING_DOWN: {AgentState.TERMINATED},
    AgentState.TERMINATED: set(),
}


@dataclass(frozen=True)
class Transition:
    ts: float
    frm: AgentState
    to: AgentState
    note: str


Listener = Callable[[Transition], None]


@dataclass
class StateMachine:
    """Drives the agent through its lifecycle with auditable transitions."""

    state: AgentState = AgentState.OFF
    history: list[Transition] = field(default_factory=list)
    _listeners: list[Listener] = field(default_factory=list, repr=False)

    def __post_init__(self) -> None:
        state_var.set(self.state.value)

    # ── public API ───────────────────────────────────────────────────────
    def add_listener(self, listener: Listener) -> None:
        self._listeners.append(listener)

    def can(self, target: AgentState) -> bool:
        return target in TRANSITIONS[self.state]

    def transition(self, target: AgentState, note: str = "") -> AgentState:
        if not self.can(target):
            raise InvalidTransitionError(
                f"Illegal transition {self.state.value} -> {target.value}"
                + (f" ({note})" if note else "")
            )
        t = Transition(ts=time.time(), frm=self.state, to=target, note=note)
        self.state = target
        self.history.append(t)
        state_var.set(target.value)
        log.debug("state %s -> %s%s", t.frm.value, t.to.value,
                  f" | {note}" if note else "")
        for listener in self._listeners:
            try:
                listener(t)
            except Exception:  # listeners must never break the machine
                log.exception("state listener raised")
        return target

    @property
    def terminal(self) -> bool:
        return self.state is AgentState.TERMINATED

    def new_run(self) -> str:
        """Stamp a fresh correlation id for a new skill execution."""
        run_id = uuid.uuid4().hex[:8]
        run_id_var.set(run_id)
        return run_id

    # ── resilience helpers ───────────────────────────────────────────────
    @staticmethod
    def backoff(attempt: int, base: float = 1.5, jitter: bool = True) -> float:
        """Exponential backoff with optional full jitter (in seconds)."""
        delay = base * (2 ** attempt)
        return random.uniform(0, delay) if jitter else delay


# ── Convenience aliases ──────────────────────────────────────────────────────
S = AgentState
