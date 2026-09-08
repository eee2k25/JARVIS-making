# J.A.R.V.I.S. — Modular Python Automation Agent

**J**ust **A** **R**ather **V**ery **I**ntelligent **S**ystem — a software-only automation
agent that fuses OS-level peripheral control, static HTML ingestion, dynamic browser
automation, and an LLM decision core into a single state-machine-driven lifecycle.

> Origin: *an idea at peanut level of how to build the JARVIS model.* This repo is the
> scaffolding that grows it.

---

## Architecture

```
                              ┌───────────────────────────────┐
                              │        JarvisAgent            │
                              │  (orchestrator + state machine)│
                              └──────┬───────────┬────────────┘
                 registers/ executes │           │ decides
        ┌────────────────────────────┘           └──────────────────────┐
        │                                                               │
┌───────▼────────┐   ┌─────────────────┐   ┌──────────────┐   ┌─────────▼────────┐
│  skills/       │   │ modules/        │   │ modules/     │   │ cognition/       │
│  perceive +    │──▶│ parser.py       │   │ gui.py       │   │ llm.py           │
│  verify        │   │ requests + bs4  │   │ PyAutoGUI    │   │ LLMBrain         │
│  (WebRecon...) │   │ DOM extraction  │   │ mouse/keys   │   │ (OpenAI-compat)  │
│                │   ├─────────────────┤   ├──────────────┤   │ OfflineBrain     │
│                │   │ browser.py      │   │ FAILSAFE on  │   │ (heuristic       │
│                │   │ Selenium WebDriver│  │ screenshots  │   │  fallback)       │
│                │   │ JS-rendered DOM │   └──────────────┘   └──────────────────┘
│                │   │ cookies, waits  │
└────────────────┘   └─────────────────┘
        ▲
        │ executes whitelisted Action plans
┌───────┴────────────────────┐
│  ActionExecutor            │  tool.action strings from the LLM are validated
│  explicit dispatch table   │  against a registry, then dispatched explicitly —
│  (no getattr on LLM text)  │  hallucinated verbs are rejected before execution.
└────────────────────────────┘
```

### The four pillars (from the original spec)

| Pillar | Module | Responsibility |
|---|---|---|
| **GUI Manipulation Interface** | `jarvis/modules/gui.py` | PyAutoGUI cursor telemetry, click events, keyboard execution — `FAILSAFE=True` enforced on every call |
| **Data Ingestion & Parsing** | `jarvis/modules/parser.py` | `requests` + BeautifulSoup4: DOM traversal helpers for titles, headings, links, tables, forms, CSS-selector batch extraction |
| **Dynamic Browser Automation** | `jarvis/modules/browser.py` | Selenium WebDriver: JS-rendered DOMs, explicit waits, form submit, JS execution, session-cookie save/load |
| **Cognitive Processing Pipeline** | `jarvis/cognition/llm.py` | Perception is piped to any OpenAI-compatible LLM; its JSON plan is validated against an action registry and executed by the agent |

---

## The state machine

Every skill run walks an explicit, auditable lifecycle. Illegal transitions raise
`InvalidTransitionError`; every hop is timestamped into `SkillResult.state_trace`.

```
                 boot                    mission loop
   OFF ──▶ BOOTING ──▶ IDLE ──▶ PERCEIVING ──▶ REASONING ──▶ ACTING ──▶ VERIFYING ──▶ IDLE
              │         │           │                          │             │
              │         │           └────── ERROR ◀────────────┴─────────────┘
              │         │                      │
              │         │              RECOVERING (backoff) ──▶ PERCEIVING (retry)
              │         │                      │ retries exhausted
              │         └──────────────────────┴──────────▶ SHUTTING_DOWN ──▶ TERMINATED
```

| State | Meaning |
|---|---|
| `BOOTING` | module init + capability probes |
| `IDLE` | healthy, awaiting mission |
| `PERCEIVING` | data ingestion (bs4 / selenium fetch) |
| `REASONING` | LLM decision pipeline |
| `ACTING` | automation triggers (PyAutoGUI / Selenium) |
| `VERIFYING` | skill post-condition checks |
| `ERROR` | a stage failed — details logged |
| `RECOVERING` | exponential backoff before retry |
| `SHUTTING_DOWN` / `TERMINATED` | graceful teardown |

**Resilience contract:** any `JarvisError` (or wrapped native library error) routes to
`ERROR → RECOVERING` with jittered exponential backoff, up to `JARVIS_MAX_RETRIES`,
then control returns to `IDLE` — the agent *never* crashes mid-mission and never
dead-locks in a state with no legal exit.

---

## Capability detection & dry-run shadow mode

Each module answers *"can I really run on this machine?"* at boot:

- no X11/Wayland display → **gui** self-reports unavailable
- no chrome/chromium binary → **browser** self-reports unavailable
- parser only needs Python → effectively always available

Unavailable modules execute in **dry-run shadow mode**: actions are logged with their
full arguments and return synthetic results, so the full perceive → reason → act →
verify cycle is demonstrable on a headless CI box — and instantly becomes *real* on a
desktop, with zero code changes. Force it explicitly with `--dry-run` or `JARVIS_DRY_RUN`.

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python main.py doctor      # probe this machine's capabilities
python main.py demo        # full offline agent cycle vs. bundled fixture site
```

Demo output (headless sandbox):

```
RESULT: SUCCESS  (1 attempt(s), 0.01s)
  brain      : offline-heuristic
  verify     : inventory OK (links=5, tables=1, forms=1, text=631 chars)
  actions:
    • system.report
    • browser.open (dry-run)
    • browser.screenshot (dry-run)
    • parser.extract

  state trace:
    OFF -> BOOTING -> IDLE -> PERCEIVING -> REASONING -> ACTING -> VERIFYING -> IDLE
```

More commands:

```bash
python main.py scrape https://example.com     # parser-only extraction (JSON)
python main.py browse https://example.com     # selenium session + screenshot
python main.py gui-test                       # pyautogui smoke test (desktop only)
python main.py demo --dry-run                 # force shadow mode everywhere
```

Tests:

```bash
python -m unittest discover -s tests -v
```

## Wiring in a real LLM brain

Any OpenAI-compatible endpoint works — set it in `.env` (see `.env.example`):

```bash
cp .env.example .env
```

| Provider | `JARVIS_LLM_BASE_URL` | example model |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| Groq | `https://api.groq.com/openai/v1` | `llama-3.3-70b-versatile` |
| OpenRouter | `https://openrouter.ai/api/v1` | `anthropic/claude-3.5-sonnet` |
| Ollama (local) | `http://localhost:11434/v1` | `llama3.1` (no API key) |

Without a key the agent falls back to `OfflineBrain` — a deterministic heuristic
planner — so the loop always completes.

## Writing a skill

Skills implement perceive + verify; the brain handles *reason*; the executor *acts*.

```python
from jarvis.skills.base import PerceptionReport, Skill, SkillContext

class PriceWatchSkill(Skill):
    name = "price_watch"
    mission = "Watch the product price and report changes."

    def __init__(self, url: str):
        self.url = url

    def perceive(self, ctx: SkillContext) -> PerceptionReport:
        parser = ctx.agent.modules["parser"]
        res = parser.get(self.url)
        price = res.soup.select_one(".price").get_text(strip=True)
        ctx.memory["price"] = price
        return PerceptionReport("parser", res.url, {"price": price})

    def verify(self, ctx: SkillContext, act_results: list[dict]) -> tuple[bool, str]:
        return ("price" in ctx.memory), f"price observed: {ctx.memory.get('price')}"

# run it
with JarvisAgent() as agent:
    agent.register(PriceWatchSkill("https://store.example/item/42"))
    result = agent.run("price_watch")
```

## Safety model

- **PyAutoGUI FAILSAFE** stays armed: slam the mouse into the top-left corner to abort.
- **Action whitelist**: the LLM can only request verbs present in `ACTION_REGISTRY`;
  unknown tools/actions raise `ReasoningError` before anything executes.
- **Explicit dispatch**: no `getattr` on model-generated strings.
- **Dry-run shadowing**: rehearse entire missions with `--dry-run` before letting
  JARVIS touch your desktop.
- **Rate pacing**: `JARVIS_GUI_PAUSE` inserts humanized delays between GUI events.

## Project layout

```
├── main.py                     # CLI: doctor | demo | scrape | browse | gui-test
├── jarvis/
│   ├── config.py               # env-driven settings (.env supported)
│   ├── state_machine.py        # FSM: transition table, listeners, backoff
│   ├── agent.py                # orchestrator + whitelisted ActionExecutor
│   ├── logging_setup.py        # structured logs with run-id + state context
│   ├── exceptions.py           # error hierarchy feeding ERROR/RECOVERING
│   ├── fixtures.py             # offline localhost fixture server
│   ├── modules/                # gui (PyAutoGUI) | parser (bs4) | browser (Selenium)
│   ├── cognition/llm.py        # LLMBrain (OpenAI-compatible) + OfflineBrain
│   └── skills/                 # base contract + WebReconSkill reference skill
├── assets/fixtures/            # bundled pages for offline demos/tests
└── tests/                      # FSM + parser unit tests
```

## Roadmap

- [ ] Voice I/O front-end (speech-to-text → skill dispatch → TTS)
- [ ] Skill scheduler (cron-like periodic missions)
- [ ] Memory layer (SQLite mission history for few-shot LLM context)
- [ ] Vision: screenshot → multimodal LLM → coordinate plans for GUI actions
- [ ] Sandboxed browser profile with persistent cookie jars
