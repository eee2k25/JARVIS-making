"""Unit tests: operator identity, long-term memory, voice engine, chat channel.

Covers the nine-step-map wiring: profile injection (step 4), SQLite mission
memory (step 5), the conversational skill (step 6/8), and the ElevenLabs
voice module with dry-run shadowing (step 8).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jarvis.config import Settings
from jarvis.memory import MemoryStore
from jarvis.modules.voice import VoiceModule
from jarvis.profile import DEFAULT_PROFILE, OperatorProfile


def _settings(**kw):
    kw.setdefault("llm_api_key", "")
    kw.setdefault("memory_db", ":memory:")
    kw.setdefault("max_retries", 0)
    return Settings(**kw)


class TestOperatorProfile(unittest.TestCase):
    def test_default_assets_profile_loads(self):
        profile = OperatorProfile.load(_settings())
        self.assertTrue(profile.name)
        self.assertIn("name:", profile.text)
        self.assertGreater(len(profile.text), 50)

    def test_custom_profile_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "me.md"
            path.write_text("name: Ada\npreferences: math and engines\n",
                            encoding="utf-8")
            profile = OperatorProfile.load(
                _settings(operator_profile=str(path)))
            self.assertEqual(profile.name, "Ada")
            self.assertEqual(profile.as_dict()["name"], "Ada")

    def test_missing_file_falls_back_to_default(self):
        profile = OperatorProfile.load(
            _settings(operator_profile="/nonexistent/profile.md"))
        self.assertEqual(profile.text, DEFAULT_PROFILE)
        self.assertEqual(profile.name, "Operator")


class TestMemoryStore(unittest.TestCase):
    def test_record_retrieve_and_snippets(self):
        mem = MemoryStore(":memory:")
        mem.record("word", "write report", True, "document OK (words=65)",
                   brain="offline-heuristic", actions=[{"tool": "word"}],
                   elapsed_s=0.4)
        mem.record("web_recon", "scan page", False, "FAILED after 2 attempts")
        self.assertEqual(mem.count(), 2)
        recent = mem.recent(limit=5)
        self.assertEqual(recent[0]["skill"], "web_recon")  # newest first
        self.assertFalse(recent[0]["success"])
        snippets = mem.context_snippets()
        self.assertEqual(len(snippets), 2)
        self.assertIn("word -> SUCCESS", snippets[0])      # oldest first
        self.assertIn("web_recon -> FAILURE", snippets[1])

    def test_stats_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "mem.db")
            with MemoryStore(db) as mem:
                mem.record("excel", "build sheet", True, "workbook OK")
            with MemoryStore(db) as mem:  # reopened from disk
                self.assertEqual(mem.count(), 1)
                stats = mem.stats()
                self.assertEqual(stats["missions"], 1)
                self.assertEqual(stats["successes"], 1)
                self.assertEqual(stats["failures"], 0)


class TestVoiceModule(unittest.TestCase):
    def test_capability_without_key_is_shadow(self):
        voice = VoiceModule(_settings())
        self.assertFalse(voice.capability.available)
        self.assertTrue(voice.dry_run)

    def test_speak_shadows_without_key(self):
        voice = VoiceModule(_settings())
        res = voice.speak("At your service.")
        self.assertTrue(res["dry_run"])
        self.assertEqual(res["action"], "speak")

    def test_speak_rejects_empty_text(self):
        from jarvis.exceptions import ActionError

        voice = VoiceModule(_settings())
        with self.assertRaises(ActionError):
            voice.speak("   ")

    def test_capability_reports_configured_voice(self):
        voice = VoiceModule(_settings(elevenlabs_api_key="test-key"))
        self.assertTrue(voice.capability.available)
        self.assertIn("ElevenLabs", voice.capability.detail)


class TestConverseSkillCycle(unittest.TestCase):
    def test_chat_cycle_reply_plus_memory(self):
        from jarvis import JarvisAgent
        from jarvis.skills.conversation import ConverseSkill

        with JarvisAgent(_settings()) as agent:
            agent.register(ConverseSkill())
            result = agent.run("converse", utterance="status report")

            self.assertTrue(result.success, result.summary)
            reply = next(a["reported"] for a in result.actions_executed
                         if "reported" in a)
            self.assertIn("Operator", reply)        # identity injected
            self.assertIn("status report", reply)   # heard the utterance
            speak = [a for a in result.actions_executed
                     if a["tool"] == "voice"]
            self.assertTrue(speak and speak[0].get("dry_run"))
            self.assertEqual(agent.memory.count(), 1)  # step 5 recorded it

    def test_chat_memory_grows_across_utterances(self):
        from jarvis import JarvisAgent
        from jarvis.skills.conversation import ConverseSkill

        with JarvisAgent(_settings()) as agent:
            agent.register(ConverseSkill())
            agent.run("converse", utterance="first question")
            result = agent.run("converse", utterance="second question")
            reply = next(a["reported"] for a in result.actions_executed
                         if "reported" in a)
            self.assertEqual(agent.memory.count(), 2)
            self.assertIn("1 mission memory fragment", reply)

    def test_empty_utterance_fails_gracefully(self):
        from jarvis import JarvisAgent
        from jarvis.skills.conversation import ConverseSkill

        with JarvisAgent(_settings()) as agent:
            agent.register(ConverseSkill())
            result = agent.run("converse", utterance="   ")
            self.assertFalse(result.success)   # resilience: no crash, no lockup
            self.assertTrue(result.errors)


if __name__ == "__main__":
    unittest.main()
