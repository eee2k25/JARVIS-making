#!/usr/bin/env python3
"""J.A.R.V.I.S. — CLI entry point.

Usage:
    python main.py doctor              # environment capability report
    python main.py demo                # full offline perceive->reason->act cycle
    python main.py scrape <url>        # parser-only extraction
    python main.py browse <url>        # selenium session against a URL
    python main.py gui-test            # pyautogui smoke test (desktop only)
    python main.py run <skill> --url X # run a registered skill
"""

from __future__ import annotations

import argparse
import json
import sys

from jarvis import JarvisAgent, __version__
from jarvis.config import Settings
from jarvis.fixtures import FixtureServer
from jarvis.logging_setup import get_logger
from jarvis.skills.recon import WebReconSkill

log = get_logger("jarvis.cli")


# ── commands ─────────────────────────────────────────────────────────────────
def cmd_doctor(_args: argparse.Namespace) -> int:
    settings = Settings.load()
    agent = JarvisAgent(settings)
    from jarvis.cognition.llm import LLMBrain

    print(f"\n  J.A.R.V.I.S. {__version__} — capability report\n  " + "─" * 46)
    for name, module in agent.modules.items():
        mark = "✓" if module.capability.available else "✗"
        mode = "dry-run shadow" if module.dry_run else "live"
        print(f"  [{mark}] {name:<8} {module.capability.detail}  -> mode: {mode}")
    brain = "configured" if settings.llm_api_key else "not configured (OfflineBrain fallback)"
    print(f"  [{'✓' if settings.llm_api_key else '!'}] brain    "
          f"{settings.llm_model} @ {settings.llm_base_url} -> {brain}")
    if isinstance(agent.brain, LLMBrain):
        pass
    print()
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    """Full state-machine cycle against the bundled fixture site (offline-safe)."""
    settings = Settings.load()
    with FixtureServer() as server, \
         JarvisAgent(settings, dry_run=args.dry_run) as agent:
        target = server.page("control_panel.html")
        print(f"\n  J.A.R.V.I.S. demo — target: {target}\n")

        agent.register(WebReconSkill(url=target))
        result = agent.run("web_recon")

        print("\n  " + "═" * 60)
        print(f"  RESULT: {'SUCCESS' if result.success else 'FAILURE'}"
              f"  ({result.attempts} attempt(s), {result.elapsed_s}s)")
        print(f"  brain      : {result.brain}")
        if result.rationale:
            print(f"  rationale  : {result.rationale}")
        print(f"  verify     : {result.summary}")
        print("  actions:")
        for a in result.actions_executed:
            flag = " (dry-run)" if a.get("dry_run") else ""
            print(f"    • {a['tool']}.{a['action']}{flag}")
        if result.errors:
            print("  errors:")
            for e in result.errors:
                print(f"    ! {e}")
        print("\n  state trace:")
        for line in result.state_trace:
            print(f"    {line}")
        print()
        return 0 if result.success else 1


def cmd_scrape(args: argparse.Namespace) -> int:
    settings = Settings.load()
    agent = JarvisAgent(settings, dry_run=args.dry_run).boot()
    parser = agent.modules["parser"]
    res = parser.get(args.url)
    payload = {
        "url": res.url,
        "status": res.status_code,
        "title": parser.title(res.soup),
        "headings": parser.headings(res.soup),
        "links": parser.find_links(res.soup, base_url=args.url)[:20],
        "tables": parser.find_tables(res.soup)[:3],
        "forms": parser.find_forms(res.soup),
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    agent.shutdown()
    return 0 if res.ok else 2


def cmd_browse(args: argparse.Namespace) -> int:
    settings = Settings.load()
    agent = JarvisAgent(settings, dry_run=args.dry_run).boot()
    browser = agent.modules["browser"]
    try:
        info = browser.open(args.url)
        print(json.dumps({"opened": info, "cookies": 0 if browser.dry_run
                          else len(browser._d().get_cookies())}, indent=2))
        shot = browser.screenshot()
        print(json.dumps(shot, indent=2))
        code = 0
    finally:
        agent.shutdown()
    return code


def cmd_gui_test(args: argparse.Namespace) -> int:
    agent = JarvisAgent(Settings.load(), dry_run=args.dry_run).boot()
    gui = agent.modules["gui"]
    print(json.dumps({
        "capability": str(gui.capability),
        "screen": gui.size(),
        "cursor": gui.position(),
    }, indent=2))
    agent.shutdown()
    return 0


# ── wiring ───────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jarvis",
                                description="J.A.R.V.I.S. automation agent")
    p.add_argument("--dry-run", action="store_true", default=None,
                   help="force dry-run shadow mode (default: auto per-module)")
    p.add_argument("--log-level", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("doctor", help="probe environment capabilities").set_defaults(fn=cmd_doctor)
    sub.add_parser("demo", help="full offline agent cycle (state machine)").set_defaults(fn=cmd_demo)

    s = sub.add_parser("scrape", help="parse a URL with requests+bs4")
    s.add_argument("url")
    s.set_defaults(fn=cmd_scrape)

    b = sub.add_parser("browse", help="open a URL with selenium")
    b.add_argument("url")
    b.set_defaults(fn=cmd_browse)

    sub.add_parser("gui-test", help="pyautogui smoke test").set_defaults(fn=cmd_gui_test)
    return p


def main(argv: list[str] | None = None) -> int:
    # keep unicode JSON pretty on C-locale pipes
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.log_level:
        import os
        os.environ["JARVIS_LOG_LEVEL"] = args.log_level
    try:
        return args.fn(args)
    except KeyboardInterrupt:
        print("\n[jarvis] interrupted — FAILSAFE respected")
        return 130


if __name__ == "__main__":
    sys.exit(main())
