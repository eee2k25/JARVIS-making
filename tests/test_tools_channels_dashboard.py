"""Unit tests: connected tools (email/calendar), channels (Telegram/Slack),
the daily brief skill, and the dashboard console (step 9).

Everything credential-gated must shadow cleanly here; the calendar ICS engine
and the dashboard loop are real on any machine.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.request
from pathlib import Path

from jarvis.cognition.llm import ACTION_REGISTRY
from jarvis.config import Settings
from jarvis.modules.calendar import CalendarModule
from jarvis.modules.email_client import EmailModule
from jarvis.modules.slack import SlackModule
from jarvis.modules.telegram import TelegramModule


def _settings(**kw):
    kw.setdefault("llm_api_key", "")
    kw.setdefault("memory_db", ":memory:")
    kw.setdefault("max_retries", 0)
    return Settings(**kw)


class TestToolRegistry(unittest.TestCase):
    def test_tools_channels_registered(self):
        self.assertEqual(ACTION_REGISTRY["email"],
                         {"inbox", "search", "read", "send"})
        self.assertEqual(ACTION_REGISTRY["calendar"],
                         {"create", "open", "events", "upcoming",
                          "add_event", "save"})
        self.assertEqual(ACTION_REGISTRY["telegram"], {"send", "updates"})
        self.assertEqual(ACTION_REGISTRY["slack"], {"send"})


class TestCalendarModule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "agenda.ics"
        self.cal = CalendarModule(_settings())

    def test_round_trip_events(self):
        self.cal.create(str(self.path))
        self.cal.add_event("Standup", "2026-10-01T09:30:00",
                           location="Room 4", notes="daily")
        self.cal.add_event("Launch", "2026-10-02", notes="all-day milestone")
        saved = self.cal.save()
        self.assertTrue(Path(saved["saved"]).exists())

        fresh = CalendarModule(_settings())
        fresh.open(str(self.path))
        res = fresh.events()
        self.assertEqual(res["count"], 2)
        titles = [e["title"] for e in res["events"]]
        self.assertEqual(titles, ["Standup", "Launch"])
        self.assertEqual(res["events"][0]["location"], "Room 4")

    def test_upcoming_window_filters(self):
        self.cal.create(str(self.path))
        self.cal.add_event("Tomorrow", "2026-10-01T10:00:00")
        self.cal.add_event("Next month", "2026-11-15T10:00:00")
        win = self.cal.events(start="2026-10-01T00:00:00",
                              end="2026-10-31T23:59:59")
        self.assertEqual([e["title"] for e in win["events"]], ["Tomorrow"])

    def test_bad_input_rejected(self):
        from jarvis.exceptions import ActionError

        self.cal.create(str(self.path))
        with self.assertRaises(ActionError):
            self.cal.add_event("", "2026-10-01")
        with self.assertRaises(ActionError):
            self.cal.add_event("X", "not-a-date")
        with self.assertRaises(ActionError):
            self.cal.add_event("Backwards", "2026-10-02", "2026-10-01")


class TestCredentialGatedModules(unittest.TestCase):
    def test_email_shadow_without_creds(self):
        email = EmailModule(_settings())
        self.assertFalse(email.capability.available)
        self.assertTrue(email.inbox()["dry_run"])
        self.assertTrue(email.send("a@b.c", "hi", "body")["dry_run"])

    def test_email_capability_with_creds(self):
        email = EmailModule(_settings(
            email_address="me@example.com", email_password="secret",
            email_imap_host="imap.example.com",
            email_smtp_host="smtp.example.com"))
        self.assertTrue(email.capability.available)
        self.assertIn("imap.example.com", email.capability.detail)

    def test_channels_shadow_without_config(self):
        for mod in (TelegramModule(_settings()), SlackModule(_settings())):
            self.assertFalse(mod.capability.available)
            self.assertTrue(mod.send("status update")["dry_run"])

    def test_channels_capability_with_config(self):
        tg = TelegramModule(_settings(telegram_bot_token="t",
                                      telegram_chat_id="42"))
        sl = SlackModule(_settings(slack_webhook_url="https://hooks/x"))
        self.assertTrue(tg.capability.available)
        self.assertTrue(sl.capability.available)
        self.assertFalse(tg.dry_run)
        self.assertFalse(sl.dry_run)


class TestDailyBriefSkillCycle(unittest.TestCase):
    def test_brief_cycle_composes_and_records(self):
        from jarvis import JarvisAgent
        from jarvis.skills.briefing import DailyBriefSkill

        with JarvisAgent(_settings()) as agent:
            agent.register(DailyBriefSkill())
            result = agent.run("daily_brief")

            self.assertTrue(result.success, result.summary)
            brief = next(a["reported"] for a in result.actions_executed
                         if "reported" in a)
            self.assertIn("daily brief", brief)
            self.assertIn("Operator", brief)          # identity injected
            self.assertIn("mission fragment", brief)  # memory-aware
            self.assertEqual(agent.memory.count(), 1)


class TestDashboard(unittest.TestCase):
    def test_status_chat_memory_endpoints(self):
        from jarvis.dashboard import DashboardServer

        with DashboardServer(_settings(), port=0) as server:
            base = server.url

            with urllib.request.urlopen(f"{base}/api/status") as resp:
                status = json.load(resp)
            self.assertIn("modules", status)
            self.assertEqual(status["memory"]["missions"], 0)
            names = [m["name"] for m in status["modules"]]
            for expected in ("word", "excel", "voice", "email", "calendar",
                             "telegram", "slack"):
                self.assertIn(expected, names)

            req = urllib.request.Request(
                f"{base}/api/chat",
                data=json.dumps({"utterance": "ping"}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req) as resp:
                chat = json.load(resp)
            self.assertTrue(chat["success"])
            self.assertIn("ping", chat["reply"])

            with urllib.request.urlopen(f"{base}/api/memory?limit=5") as resp:
                mem = json.load(resp)
            self.assertEqual(mem["missions"][0]["skill"], "converse")

            with urllib.request.urlopen(base) as resp:
                page = resp.read().decode()
            self.assertIn("J.A.R.V.I.S", page)


if __name__ == "__main__":
    unittest.main()
