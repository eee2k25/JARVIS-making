"""Unit tests: MS Office engines (Word / PowerPoint / Excel) + office skills.

Covers the action whitelist, each file-engine round trip (real Open XML
artifacts in a temp dir), app-engine dry-run shadowing, and full
perceive -> reason -> act -> verify agent cycles via the OfflineBrain.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from jarvis.cognition.llm import ACTION_REGISTRY, Action, OfflineBrain
from jarvis.config import Settings
from jarvis.exceptions import ReasoningError
from jarvis.modules.word import WordModule

OFFICE_TOOLS = ("word", "excel", "powerpoint")


class TestOfficeActionRegistry(unittest.TestCase):
    def test_office_tools_registered(self):
        for tool in OFFICE_TOOLS:
            self.assertIn(tool, ACTION_REGISTRY)
        self.assertIn("save", ACTION_REGISTRY["word"])
        self.assertIn("add_slide", ACTION_REGISTRY["powerpoint"])
        self.assertIn("set_formula", ACTION_REGISTRY["excel"])

    def test_valid_office_action_passes(self):
        Action("word", "add_heading", {"text": "Q3", "level": 1}).validate()
        Action("powerpoint", "add_slide", {"title": "Status"}).validate()
        Action("excel", "set_formula", {"cell": "B2", "formula": "=SUM(A1:A9)"}).validate()

    def test_hallucinated_office_verb_rejected(self):
        with self.assertRaises(ReasoningError):
            Action("word", "run_macro", {}).validate()
        with self.assertRaises(ReasoningError):
            Action("excel", "vlookup", {}).validate()
        with self.assertRaises(ReasoningError):
            Action("powerpoint", "apply_template", {}).validate()


class TestWordModule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "report.docx"
        self.word = WordModule(Settings(llm_api_key=""))

    def test_round_trip_create_edit_save_read(self):
        self.word.create(str(self.path), title="Ops Report")
        self.word.add_heading("Ops Report", level=1)
        self.word.add_text("Reactor output holds at 3.1 gigawatts.")
        self.word.add_table([["Module", "State"], ["gui", "READY"]])
        saved = self.word.save()
        self.assertTrue(Path(saved["saved"]).exists())
        self.assertGreater(saved["bytes"], 1000)

        fresh = WordModule(Settings(llm_api_key=""))
        fresh.open(str(self.path))
        inv = fresh.read()
        self.assertEqual(inv["title"], "Ops Report")
        self.assertEqual([h["text"] for h in inv["headings"]], ["Ops Report"])
        self.assertEqual(inv["tables"][0][0], ["Module", "State"])
        self.assertGreaterEqual(inv["word_count"], 8)

    def test_replace_swaps_text(self):
        self.word.create(str(self.path))
        self.word.add_text("status is DRAFT")
        self.word.replace("DRAFT", "FINAL")
        inv = self.word.read()
        self.assertIn("FINAL", inv["paragraphs"][0]["text"])

    def test_app_engine_verbs_shadow_without_ms_office(self):
        self.word.create(str(self.path))
        self.word.add_text("payload")
        self.word.save()
        for res in (self.word.export_pdf(), self.word.launch()):
            self.assertTrue(res["dry_run"], "app-engine verbs must shadow "
                            "where the real MS Word app is absent")
            self.assertIn("action", res)


class TestWordSkillCycle(unittest.TestCase):
    """Full perceive -> reason -> act -> verify cycle through JarvisAgent."""

    def _settings(self):
        # no API key -> OfflineBrain; zero retries -> fast, deterministic
        return Settings(llm_api_key="", max_retries=0)

    def test_offline_brain_realizes_word_blueprint(self):
        plan = OfflineBrain().decide({
            "source": "word", "url": "/tmp/x.docx", "target": "/tmp/x.docx",
            "inventory": {"exists": False}, "stats": {"word_count": 0},
            "blueprint": {"title": "R", "paragraphs": ["p1"],
                          "table": [["a", "b"]]},
        }, "write the report")
        for action in plan.actions:
            action.validate()
        tools = [(a.tool, a.action) for a in plan.actions]
        self.assertEqual(tools[0], ("system", "report"))
        self.assertIn(("word", "create"), tools)
        self.assertIn(("word", "add_table"), tools)
        self.assertEqual(tools[-1], ("word", "save"))

    def test_agent_cycle_writes_real_docx(self):
        from jarvis.skills.office import WordSkill

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cycle.docx"
            skill = WordSkill(path=target, blueprint={
                "title": "Cycle Report",
                "paragraphs": ["Automated body text for the mission."],
                "table": [["k", "v"], ["attempts", "1"]],
            })
            from jarvis import JarvisAgent

            with JarvisAgent(self._settings()) as agent:
                agent.register(skill)
                result = agent.run("word")

            self.assertTrue(result.success, result.summary)
            self.assertTrue(target.exists(), "cycle must leave a .docx behind")
            self.assertEqual(result.actions_executed[0]["tool"], "system")
            word_actions = [a for a in result.actions_executed
                            if a["tool"] == "word"]
            self.assertFalse(any(a.get("dry_run") for a in word_actions))

            probe = WordModule(self._settings())
            probe.open(str(target))
            inv = probe.read()
            self.assertEqual(inv["headings"][0]["text"], "Cycle Report")
            self.assertEqual(inv["tables"][0][0], ["k", "v"])

    def test_agent_cycle_forced_dry_run_touches_nothing(self):
        from jarvis.skills.office import WordSkill

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "shadow.docx"
            skill = WordSkill(path=target, blueprint={
                "title": "Shadow", "paragraphs": ["never written"],
            })
            from jarvis import JarvisAgent

            with JarvisAgent(self._settings(), dry_run=True) as agent:
                agent.register(skill)
                result = agent.run("word")

            self.assertTrue(result.success, result.summary)
            self.assertIn("shadow", result.summary.lower())
            self.assertFalse(target.exists(), "dry-run must not write artifacts")

    def test_verify_requires_artifact_when_blueprint_given(self):
        from jarvis.skills.base import SkillContext
        from jarvis.skills.office import WordSkill

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "missing.docx"
            skill = WordSkill(path=target, blueprint={"title": "X"})
            from jarvis import JarvisAgent

            with JarvisAgent(self._settings()) as agent:
                ctx = SkillContext(agent=agent, mission=skill.mission)
                ctx.memory.update(target=str(target),
                                  blueprint=skill.blueprint,
                                  stats={"word_count": 0})
                ok, note = skill.verify(ctx, [
                    {"dry_run": False, "saved": str(target)},
                ])
            self.assertFalse(ok)
            self.assertIn("missing", note)


if __name__ == "__main__":
    unittest.main()
