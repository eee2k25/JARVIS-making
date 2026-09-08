"""J.A.R.V.I.S. — Modular Python automation agent.

A state-machine driven agent that fuses:
  * PyAutoGUI      — OS-level mouse/keyboard automation
  * BeautifulSoup  — static HTML ingestion & DOM extraction
  * Selenium       — dynamic, JS-rendered browser automation
  * LLM pipeline   — cognitive decision core (OpenAI-compatible REST)
"""

__version__ = "0.1.0"

from .agent import JarvisAgent, SkillResult
from .state_machine import AgentState, StateMachine
from .exceptions import JarvisError

__all__ = [
    "JarvisAgent",
    "SkillResult",
    "AgentState",
    "StateMachine",
    "JarvisError",
    "__version__",
]
