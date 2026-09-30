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

### The five pillars

| Pillar | Module | Responsibility |
|---|---|---|
| **GUI Manipulation Interface** | `jarvis/modules/gui.py` | PyAutoGUI cursor telemetry, click events, keyboard execution — `FAILSAFE=True` enforced on every call |
| **Data Ingestion & Parsing** | `jarvis/modules/parser.py` | `requests` + BeautifulSoup4: DOM traversal helpers for titles, headings, links, tables, forms, CSS-selector batch extraction |
| **Dynamic Browser Automation** | `jarvis/modules/browser.py` | Selenium WebDriver: JS-rendered DOMs, explicit waits, form submit, JS execution, session-cookie save/load |
| **MS Office Automation** | `jarvis/modules/{word,powerpoint,excel}.py` | Word / PowerPoint / Excel: create, read, edit and save real `.docx` / `.pptx` / `.xlsx` artifacts, plus real desktop-app control (`export_pdf`, `launch`) via the Windows COM bridge |
| **Cognitive Processing Pipeline** | `jarvis/cognition/llm.py` | Perception is piped to any OpenAI-compatible LLM; its JSON plan is validated against an action registry and executed by the agent |

---

## From the nine-step "build your own Jarvis" map

How the popular nine-step recipe maps onto this repo — the pieces are wired,
not wished:

| # | Recipe step | In J.A.R.V.I.S. |
|---|---|---|
| 1 | **Give it a home** | Any always-on box — it's pure Python. Run `python main.py chat` on a laptop, Mini or cloud VM and leave it up |
| 2 | **Install an agent harness** | `JarvisAgent` *is* the harness: state machine, whitelisted ActionExecutor, ERROR→RECOVERING resilience — no external agent framework needed |
| 3 | **Pick the brain** | `cognition/llm.py` — any OpenAI-compatible model (Claude via OpenRouter, Gemini, Grok, Ollama…) swapped via env; `OfflineBrain` keeps the loop alive without one |
| 4 | **Teach it who I am** | `jarvis/profile.py` + `assets/profile/operator.md` — your work, goals, preferences and boundaries injected into every LLM decision |
| 5 | **Long-term memory** | `jarvis/memory.py` — SQLite mission history (`logs/memory/jarvis.db`) fed back as few-shot context; remembers across sessions |
| 6 | **Add skills** | `jarvis/skills/` — `WebReconSkill`, `WordSkill`, `PowerPointSkill`, `ExcelSkill`, `ConverseSkill`, `DailyBriefSkill`; write your own against the 2-method contract |
| 7 | **Connect tools** | `jarvis/modules/` — browser, parser, GUI, the full MS Office suite, **email** (IMAP/SMTP) and **calendar** (iCalendar ICS) |
| 8 | **Channels + voice** | `chat` channel + **Telegram** and **Slack** bridges; `jarvis/modules/voice.py` gives it an ElevenLabs voice (TTS `speak` + Scribe `transcribe`) — British accent optional, obviously |
| 9 | **The Jarvis look** | `python main.py dashboard` — a live console: module health, mission memory, chat wired to the real agent loop, and a speak button wired to the voice |

Every one of the nine steps is now wired, not wished: pieces without credentials
run in dry-run shadow mode and light up the moment their key lands in `.env`.

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
- no MS Office / Windows COM → **word / powerpoint / excel** keep their
  cross-platform file engines live and shadow only the desktop-app verbs

Unavailable modules execute in **dry-run shadow mode**: actions are logged with their
full arguments and return synthetic results, so the full perceive → reason → act →
verify cycle is demonstrable on a headless CI box — and instantly becomes *real* on a
desktop, with zero code changes. Force it explicitly with `--dry-run` or `JARVIS_DRY_RUN`.

---

## Working with MS Office — Word, PowerPoint, Excel

Three dedicated engines wrap the Microsoft Office apps, integrated one by one:

| Engine | Module | File engine (cross-platform) | App engine (real MS app) |
|---|---|---|---|
| **Word** | `jarvis/modules/word.py` | `python-docx`: create/open/read, headings, body text, tables, find & replace, save `.docx` | `Word.Application` (COM): `export_pdf`, `launch` |
| **PowerPoint** | `jarvis/modules/powerpoint.py` | `python-pptx`: create/open/read slide inventories, title+content slides with speaker notes, embed images, save `.pptx` | `PowerPoint.Application` (COM): `export_pdf`, `launch` |
| **Excel** | `jarvis/modules/excel.py` | `openpyxl`: create/open/read, range writes, row appends, formulas, cell formatting, bar/line/pie charts, save `.xlsx` | `Excel.Application` (COM): `export_pdf`, `launch` |

**Two-engine design.** The *file* engine manipulates Open XML documents directly and
runs anywhere Python runs — this sandbox included. The *app* engine drives the actual
Word/PowerPoint/Excel desktop applications through the Windows COM bridge
(`pywin32`); on machines without Office those verbs log dry-run shadow actions and
light up automatically on a Windows rig with Office installed.

**Skills + blueprints.** Each engine has a mission skill (`jarvis/skills/office.py`)
that walks the full state-machine cycle. Blueprints describe the document to realize:

```python
from jarvis import JarvisAgent
from jarvis.skills.office import WordSkill

with JarvisAgent() as agent:
    agent.register(WordSkill("logs/office/weekly.docx", blueprint={
        "title": "Weekly Report",
        "paragraphs": ["Highlights..."],
        "table": [["Metric", "Value"], ["Uptime", "99.9%"]],
    }))
    result = agent.run("word")   # perceive -> reason -> act -> verify
```

Word/PowerPoint blueprints are *additive* on existing files (open + append) and
*generative* on missing ones (create + write + save); Excel blueprints describe the
whole sheet, so the workbook is rebuilt to avoid stale rows. Verification re-opens
the artifact and checks the blueprint's content actually landed.

**Whitelisted actions** (validated before execution, same as every other tool):

| Tool | Actions |
|---|---|
| `word` | `create`, `open`, `read`, `add_heading`, `add_text`, `add_table`, `replace`, `save`, `export_pdf`, `launch` |
| `powerpoint` | `create`, `open`, `read`, `add_slide`, `add_image`, `save`, `export_pdf`, `launch` |
| `excel` | `create`, `open`, `read`, `write`, `append_rows`, `set_formula`, `format`, `add_chart`, `save`, `export_pdf`, `launch` |

Try it from the CLI:

```bash
python main.py word          # build the sample .docx report
python main.py powerpoint    # build the sample .pptx briefing
python main.py excel         # build the sample .xlsx power budget
python main.py office-demo   # all three, one by one, in one agent session
```

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
python main.py word                           # MS Word cycle -> .docx report
python main.py powerpoint                     # MS PowerPoint cycle -> .pptx deck
python main.py excel                          # MS Excel cycle -> .xlsx workbook
python main.py office-demo                    # Word -> PowerPoint -> Excel, one by one
python main.py chat                           # talk to it (identity + memory + voice)
python main.py voice-test "At your service."  # synthesize a line (shadow w/o key)
python main.py brief                          # daily brief: calendar + inbox + memory
python main.py dashboard                      # the Jarvis console (status/chat/voice)
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
├── main.py                     # CLI: doctor | demo | scrape | browse | gui-test | word | powerpoint | excel
│                               #       | office-demo | chat | voice-test | brief | dashboard
├── jarvis/
│   ├── config.py               # env-driven settings (.env supported)
│   ├── state_machine.py        # FSM: transition table, listeners, backoff
│   ├── agent.py                # orchestrator + whitelisted ActionExecutor
│   ├── logging_setup.py        # structured logs with run-id + state context
│   ├── exceptions.py           # error hierarchy feeding ERROR/RECOVERING
│   ├── fixtures.py             # offline localhost fixture server
│   ├── profile.py              # operator identity (step 4 of the map)
│   ├── memory.py               # SQLite long-term mission memory (step 5)
│   ├── dashboard.py            # the Jarvis console — status/chat/voice UI (step 9)
│   ├── modules/                # gui (PyAutoGUI) | parser (bs4) | browser (Selenium)
│   │                           # office.py (shared MS Office foundation)
│   │                           # word.py | powerpoint.py | excel.py (Office engines)
│   │                           # voice.py (ElevenLabs TTS/STT, shadow-first)
│   │                           # email_client.py (IMAP/SMTP) | calendar.py (ICS)
│   │                           # telegram.py | slack.py (channel bridges)
│   ├── cognition/llm.py        # LLMBrain (OpenAI-compatible) + OfflineBrain
│   └── skills/                 # base + WebRecon + office + Converse + DailyBrief
├── assets/
│   ├── fixtures/               # bundled pages for offline demos/tests
│   └── profile/operator.md     # who JARVIS works for + how they like things
└── tests/                      # FSM + parser + Office + profile/memory/voice
│                               # + tools/channels/dashboard unit tests
```

## Roadmap

- [x] MS Office automation — Word, PowerPoint & Excel modules + skills (file engines everywhere, COM app engines on Windows)
- [x] Voice I/O front-end — ElevenLabs TTS/STT module + `chat` channel (mic capture pending)
- [x] Memory layer — SQLite mission history for few-shot LLM context (`jarvis/memory.py`)
- [x] Connected tools — email (IMAP/SMTP) + calendar (ICS) modules
- [x] Channels — Telegram bot + Slack webhook bridges
- [x] The Jarvis look — live console: status, memory, chat + voice (`python main.py dashboard`)
- [ ] Identity → proactive behavior (profile-driven goals, not just context)
- [ ] Inbound channel loops (Telegram long-poll listener as a daemon)
- [ ] Skill scheduler (cron-like periodic missions)
- [ ] Vision: screenshot → multimodal LLM → coordinate plans for GUI actions
- [ ] Sandboxed browser profile with persistent cookie jars
