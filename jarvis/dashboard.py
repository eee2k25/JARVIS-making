"""The Jarvis look (step 9) — a live dashboard wired to the agent.

A self-contained status/chat console served over plain HTTP (stdlib only):
agent state and module health, the mission-memory feed, a chat box that runs
the real ConverseSkill cycle per message, and a voice button that speaks the
last reply through the voice engine. Serve it with:

    python main.py dashboard            # http://localhost:8787
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__
from .agent import JarvisAgent
from .config import Settings
from .logging_setup import get_logger
from .skills.conversation import ConverseSkill

log = get_logger("jarvis.dashboard")

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>J.A.R.V.I.S. — Console</title>
<style>
  :root {
    --bg: #0d1117; --panel: #161b22; --panel2: #1c2330; --line: #2a3342;
    --text: #e6edf3; --dim: #8b98a9; --gold: #e8b339; --ok: #3fb96e;
    --bad: #d15656; --blue: #58a6ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: radial-gradient(1200px 500px at 80% -10%, #1a2233 0%, var(--bg) 55%);
    color: var(--text); font: 15px/1.55 "Segoe UI", system-ui, sans-serif;
    min-height: 100vh;
  }
  .wrap { max-width: 1080px; margin: 0 auto; padding: 28px 22px 60px; }
  header { display: flex; align-items: baseline; gap: 14px; margin-bottom: 6px; }
  h1 { font-size: 26px; letter-spacing: 6px; font-weight: 600; }
  h1 .dot { color: var(--gold); }
  .sub { color: var(--dim); letter-spacing: 1px; margin-bottom: 24px; }
  .pill {
    display: inline-flex; align-items: center; gap: 8px; padding: 5px 13px;
    border: 1px solid var(--line); border-radius: 999px; font-size: 12.5px;
    letter-spacing: 1.5px; text-transform: uppercase; color: var(--dim);
    background: var(--panel);
  }
  .pill .led { width: 9px; height: 9px; border-radius: 50%; background: var(--ok);
    box-shadow: 0 0 8px var(--ok); }
  .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; margin-top: 20px; }
  @media (max-width: 860px) { .grid { grid-template-columns: 1fr; } }
  .card {
    background: linear-gradient(180deg, var(--panel2), var(--panel));
    border: 1px solid var(--line); border-radius: 14px; padding: 18px 20px;
  }
  .card h2 {
    font-size: 12px; letter-spacing: 2.5px; text-transform: uppercase;
    color: var(--gold); margin-bottom: 13px;
  }
  .full { grid-column: 1 / -1; }
  .mods { display: grid; grid-template-columns: repeat(auto-fill, minmax(155px, 1fr)); gap: 10px; }
  .mod {
    background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
    padding: 10px 12px; font-size: 13px;
  }
  .mod b { display: block; font-size: 13.5px; letter-spacing: .6px; }
  .mod span { color: var(--dim); font-size: 11.5px; }
  .mod.live b { color: var(--ok); } .mod.shadow b { color: var(--dim); }
  .stat-row { display: flex; gap: 26px; flex-wrap: wrap; }
  .stat .n { font-size: 27px; color: var(--gold); font-weight: 600; }
  .stat .l { color: var(--dim); font-size: 11.5px; letter-spacing: 1.6px;
    text-transform: uppercase; }
  #mem li { list-style: none; padding: 7px 0; border-bottom: 1px dashed var(--line);
    font-size: 13px; color: var(--dim); }
  #mem li b { color: var(--text); font-weight: 600; }
  .okc { color: var(--ok); } .badc { color: var(--bad); }
  #chatlog { display: flex; flex-direction: column; gap: 10px; min-height: 120px;
    max-height: 330px; overflow-y: auto; padding-right: 4px; }
  .msg { padding: 10px 14px; border-radius: 12px; max-width: 82%; white-space: pre-wrap; }
  .msg.you { align-self: flex-end; background: #24344d; border: 1px solid #33507a; }
  .msg.bot { align-self: flex-start; background: var(--panel2);
    border: 1px solid var(--line); }
  .msg .who { display: block; font-size: 10.5px; letter-spacing: 1.6px;
    text-transform: uppercase; color: var(--dim); margin-bottom: 3px; }
  .chatbar { display: flex; gap: 10px; margin-top: 14px; }
  input[type=text] {
    flex: 1; background: var(--panel); color: var(--text); border: 1px solid var(--line);
    border-radius: 10px; padding: 11px 14px; font-size: 14px; outline: none;
  }
  input[type=text]:focus { border-color: var(--gold); }
  button {
    background: var(--gold); color: #1a1405; border: 0; border-radius: 10px;
    padding: 11px 18px; font-weight: 600; cursor: pointer; letter-spacing: .8px;
  }
  button.ghost { background: transparent; color: var(--gold);
    border: 1px solid var(--gold); }
  button:disabled { opacity: .5; cursor: wait; }
  footer { margin-top: 28px; color: var(--dim); font-size: 12px;
    letter-spacing: 1.2px; text-align: center; }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>J.A.R.V.I.S<span class="dot">.</span></h1>
    <span class="pill"><span class="led"></span><span id="state">booting</span></span>
    <span class="pill" id="brainpill">brain: …</span>
  </header>
  <div class="sub">Just A Rather Very Intelligent System — console</div>

  <div class="grid">
    <div class="card">
      <h2>Operators</h2>
      <div class="stat-row">
        <div class="stat"><div class="n" id="opname">—</div><div class="l">operator</div></div>
        <div class="stat"><div class="n" id="memcount">0</div><div class="l">missions remembered</div></div>
        <div class="stat"><div class="n" id="memrate">—</div><div class="l">success rate</div></div>
      </div>
    </div>
    <div class="card">
      <h2>Mission memory</h2>
      <ul id="mem"><li>no missions yet</li></ul>
    </div>

    <div class="card full">
      <h2>Module health</h2>
      <div class="mods" id="mods"></div>
    </div>

    <div class="card full">
      <h2>Conversation</h2>
      <div id="chatlog">
        <div class="msg bot"><span class="who">jarvis</span>All systems online. How may I help?</div>
      </div>
      <div class="chatbar">
        <input type="text" id="say" placeholder="Speak to J.A.R.V.I.S…"
               autocomplete="off">
        <button id="send">Send</button>
        <button class="ghost" id="speak">🔊 Speak reply</button>
      </div>
    </div>
  </div>
  <footer id="foot">…</footer>
</div>
<script>
const $ = (id) => document.getElementById(id);
let lastReply = "All systems online. How may I help?";

async function refresh() {
  try {
    const s = await (await fetch("/api/status")).json();
    $("state").textContent = s.state;
    $("opname").textContent = s.operator.name;
    $("brainpill").textContent = "brain: " + s.brain;
    $("memcount").textContent = s.memory.missions;
    const rate = s.memory.missions
      ? Math.round(100 * s.memory.successes / s.memory.missions) + "%" : "—";
    $("memrate").textContent = rate;
    $("foot").textContent = "J.A.R.V.I.S. " + s.version + " · memory: " + s.memory.db;
    $("mods").innerHTML = s.modules.map(m =>
      `<div class="mod ${m.available ? "live" : "shadow"}"><b>${m.name}</b>
       <span>${m.available ? "LIVE" : "SHADOW"} · ${m.detail}</span></div>`).join("");
  } catch (e) { /* keep last view */ }
  try {
    const mem = await (await fetch("/api/memory?limit=6")).json();
    $("mem").innerHTML = mem.missions.length
      ? mem.missions.map(m =>
          `<li><b class="${m.success ? "okc" : "badc"}">${m.skill}</b>
           ${m.summary.slice(0, 72)}</li>`).join("")
      : "<li>no missions yet</li>";
  } catch (e) {}
}

function bubble(who, text) {
  const div = document.createElement("div");
  div.className = "msg " + (who === "you" ? "you" : "bot");
  div.innerHTML = `<span class="who">${who === "you" ? "you" : "jarvis"}</span>`;
  div.append(document.createTextNode(text));
  $("chatlog").append(div);
  $("chatlog").scrollTop = $("chatlog").scrollHeight;
}

async function chat(text) {
  if (!text.trim()) return;
  bubble("you", text);
  $("send").disabled = true;
  try {
    const r = await (await fetch("/api/chat", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({utterance: text}),
    })).json();
    lastReply = r.reply || "(no reply)";
    bubble("bot", lastReply);
    refresh();
  } catch (e) {
    bubble("bot", "channel error: " + e);
  }
  $("send").disabled = false;
}

$("send").onclick = () => { chat($("say").value); $("say").value = ""; };
$("say").addEventListener("keydown", e => {
  if (e.key === "Enter") { chat($("say").value); $("say").value = ""; }
});
$("speak").onclick = async () => {
  $("speak").disabled = true;
  try {
    const r = await (await fetch("/api/voice", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({text: lastReply}),
    })).json();
    if (r.audio) new Audio("/audio/" + r.audio.split("/").pop()).play();
  } catch (e) {}
  $("speak").disabled = false;
};

refresh();
setInterval(refresh, 12000);
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    """JSON API + console page for the live agent."""

    server_version = "JarvisDashboard/1.0"

    def log_message(self, *args, **kwargs):  # noqa: N802 - quiet like fixtures
        pass

    # ── helpers ──────────────────────────────────────────────────────────
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    @property
    def jarvis(self) -> JarvisAgent:
        return self.server.jarvis  # type: ignore[attr-defined]

    # ── routes ───────────────────────────────────────────────────────────
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif url.path == "/api/status":
            self._json(self._status())
        elif url.path == "/api/memory":
            limit = int(parse_qs(url.query).get("limit", ["6"])[0])
            self._json({"missions": self.jarvis.memory.recent(limit)})
        elif url.path.startswith("/audio/"):
            self._audio(url.path.split("/audio/", 1)[1])
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad JSON"}, 400)
        if url.path == "/api/chat":
            self._chat(body)
        elif url.path == "/api/voice":
            self._voice(body)
        else:
            self._json({"error": "not found"}, 404)

    # ── handlers ─────────────────────────────────────────────────────────
    def _status(self) -> dict:
        agent = self.jarvis
        return {
            "version": __version__,
            "state": agent.sm.state.value,
            "brain": agent.brain.name,
            "operator": agent.profile.as_dict() | {"profile": ""},
            "memory": agent.memory.stats(),
            "modules": [
                {"name": name, "available": m.capability.available,
                 "detail": m.capability.detail,
                 "mode": "shadow" if m.dry_run else "live"}
                for name, m in agent.modules.items()
            ],
        }

    def _chat(self, body: dict) -> None:
        utterance = str(body.get("utterance", "")).strip()
        if not utterance:
            return self._json({"error": "empty utterance"}, 400)
        with self.server.agent_lock:  # type: ignore[attr-defined]
            result = self.jarvis.run("converse", utterance=utterance)
        reply = next((a.get("reported") for a in result.actions_executed
                      if a.get("reported")), result.summary)
        self._json({"reply": reply, "success": result.success,
                    "brain": result.brain})

    def _voice(self, body: dict) -> None:
        text = str(body.get("text", "")).strip()
        if not text:
            return self._json({"error": "empty text"}, 400)
        with self.server.agent_lock:  # type: ignore[attr-defined]
            res = self.jarvis.modules["voice"].speak(text)
        self._json(res)

    def _audio(self, name: str) -> None:
        safe = Path(name).name  # never escape the voice directory
        target = (Path(self.jarvis.settings.voice_output_dir or "logs/voice")
                  / safe)
        if not safe or not target.exists():
            return self._json({"error": "audio not found"}, 404)
        self._send(200, target.read_bytes(), "audio/mpeg")


class DashboardServer:
    """Owns one live JarvisAgent and serves the console around it."""

    def __init__(self, settings: Settings | None = None,
                 dry_run: bool | None = None,
                 host: str | None = None, port: int | None = None) -> None:
        self.settings = settings or Settings.load()
        self.agent = JarvisAgent(self.settings, dry_run=dry_run)
        self.host = host or self.settings.dashboard_host or "0.0.0.0"
        self.port = port if port is not None else self.settings.dashboard_port
        self._httpd = ThreadingHTTPServer((self.host, self.port), _Handler)
        self._httpd.jarvis = self.agent          # type: ignore[attr-defined]
        self._httpd.agent_lock = threading.Lock()  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        show = "localhost" if host in ("0.0.0.0", "::") else host
        return f"http://{show}:{port}"

    def start(self) -> "DashboardServer":
        self.agent.boot()
        self.agent.register(ConverseSkill())
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="jarvis-dashboard")
        self._thread.start()
        log.info("dashboard serving at %s", self.url)
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self.agent.shutdown(reason="dashboard stop")

    def __enter__(self) -> "DashboardServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
