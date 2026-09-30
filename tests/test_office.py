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
from jarvis.modules.excel import ExcelModule
from jarvis.modules.powerpoint import PowerPointModule
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
        return Settings(llm_api_key="", max_retries=0, memory_db=":memory:")

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


class TestPowerPointModule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "briefing.pptx"
        self.ppt = PowerPointModule(Settings(llm_api_key=""))

    def test_round_trip_deck_build_and_read(self):
        self.ppt.create(str(self.path), title="Status Briefing")
        self.ppt.add_slide("Agenda", ["one", "two"], notes="speaker cue")
        self.ppt.add_slide("Numbers", ["3.1 GW output"])
        saved = self.ppt.save()
        self.assertTrue(Path(saved["saved"]).exists())
        self.assertGreater(saved["bytes"], 1000)

        fresh = PowerPointModule(Settings(llm_api_key=""))
        fresh.open(str(self.path))
        inv = fresh.read()
        self.assertEqual(inv["title"], "Status Briefing")
        self.assertEqual(inv["slide_count"], 2)
        self.assertEqual(inv["slides"][0]["title"], "Agenda")
        self.assertEqual(inv["slides"][0]["bullets"], ["one", "two"])
        self.assertEqual(inv["slides"][0]["notes"], "speaker cue")
        self.assertIn("3.1 GW output", inv["slides"][1]["bullets"])

    def test_add_image_requires_existing_slide(self):
        self.ppt.create(str(self.path))
        from jarvis.exceptions import ActionError

        with self.assertRaises(ActionError):
            self.ppt.add_image("nope.png")
        self.ppt.add_slide("Pic", ["visual"])
        with self.assertRaises(ActionError):
            self.ppt.add_image(str(Path(self.tmp.name) / "missing.png"))

    def test_app_engine_verbs_shadow_without_ms_office(self):
        self.ppt.create(str(self.path))
        self.ppt.add_slide("S")
        self.ppt.save()
        for res in (self.ppt.export_pdf(), self.ppt.launch()):
            self.assertTrue(res["dry_run"])


class TestPowerPointSkillCycle(unittest.TestCase):
    def _settings(self):
        return Settings(llm_api_key="", max_retries=0, memory_db=":memory:")

    def test_offline_brain_realizes_deck_blueprint(self):
        plan = OfflineBrain().decide({
            "source": "powerpoint", "url": "/tmp/x.pptx",
            "target": "/tmp/x.pptx", "inventory": {"exists": False},
            "stats": {"slides": 0},
            "blueprint": {"slides": [{"title": "A", "bullets": ["b1"]}]},
        }, "build the deck")
        for action in plan.actions:
            action.validate()
        tools = [(a.tool, a.action) for a in plan.actions]
        self.assertEqual(tools[0], ("system", "report"))
        self.assertIn(("powerpoint", "add_slide"), tools)
        self.assertEqual(tools[-1], ("powerpoint", "save"))

    def test_agent_cycle_writes_real_pptx(self):
        from jarvis import JarvisAgent
        from jarvis.skills.office import PowerPointSkill

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cycle.pptx"
            skill = PowerPointSkill(path=target, blueprint={
                "slides": [
                    {"title": "Cycle Title", "bullets": ["a", "b"]},
                    {"title": "Second Slide", "bullets": ["c"], "notes": "n"},
                ],
            })
            with JarvisAgent(self._settings()) as agent:
                agent.register(skill)
                result = agent.run("powerpoint")

            self.assertTrue(result.success, result.summary)
            self.assertTrue(target.exists())
            probe = PowerPointModule(self._settings())
            probe.open(str(target))
            inv = probe.read()
            self.assertEqual(inv["slide_count"], 2)
            self.assertIn("Cycle Title", [s["title"] for s in inv["slides"]])

    def test_agent_cycle_forced_dry_run_touches_nothing(self):
        from jarvis import JarvisAgent
        from jarvis.skills.office import PowerPointSkill

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "shadow.pptx"
            skill = PowerPointSkill(path=target, blueprint={
                "slides": [{"title": "Shadow"}],
            })
            with JarvisAgent(self._settings(), dry_run=True) as agent:
                agent.register(skill)
                result = agent.run("powerpoint")

            self.assertTrue(result.success, result.summary)
            self.assertFalse(target.exists())


class TestExcelModule(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "budget.xlsx"
        self.xl = ExcelModule(Settings(llm_api_key=""))

    def test_round_trip_grid_formulas_format_chart(self):
        self.xl.create(str(self.path), title="Power Budget",
                       sheet="Power Budget")
        self.xl.write("A1", [["Item", "Draw (W)", "Hours", "Energy (Wh)"],
                             ["core", 3100, 24, None],
                             ["sensors", 220, 24, None]])
        self.xl.set_formula("D2", "=B2*C2")
        self.xl.set_formula("D3", "=B3*C3")
        self.xl.format("A1:D1", bold=True, fill="FF2060", col_width=18)
        self.xl.add_chart("bar", title="Draw", data_ref="B2:B3",
                          cats_ref="A2:A3", anchor="F2")
        saved = self.xl.save()
        self.assertTrue(Path(saved["saved"]).exists())
        self.assertGreater(saved["bytes"], 1000)

        fresh = ExcelModule(Settings(llm_api_key=""))
        fresh.open(str(self.path))
        inv = fresh.read(sheet="Power Budget")
        self.assertEqual(inv["sheets"], ["Power Budget"])
        self.assertEqual(inv["rows"][0][0], "Item")
        self.assertEqual(inv["rows"][1][1], 3100)
        self.assertEqual(inv["formulas"]["D2"], "=B2*C2")
        self.assertEqual(inv["formulas"]["D3"], "=B3*C3")

    def test_append_rows_grows_sheet(self):
        self.xl.create(str(self.path))
        self.xl.write("A1", [["h"]])
        res = self.xl.append_rows([[1], [2], [3]])
        self.assertEqual(res["appended"], 3)
        self.assertEqual(self.xl.read()["max_row"], 4)

    def test_bad_ranges_rejected(self):
        from jarvis.exceptions import ActionError

        self.xl.create(str(self.path))
        with self.assertRaises(ActionError):
            self.xl.write("not-a-cell", [[1]])
        with self.assertRaises(ActionError):
            self.xl.format("::bad::")
        with self.assertRaises(ActionError):
            self.xl.add_chart("scatter", data_ref="A1:A2")
        with self.assertRaises(ActionError):
            self.xl.read(sheet="Nope")

    def test_app_engine_verbs_shadow_without_ms_office(self):
        self.xl.create(str(self.path))
        self.xl.write("A1", [[1]])
        self.xl.save()
        for res in (self.xl.export_pdf(), self.xl.launch()):
            self.assertTrue(res["dry_run"])


class TestExcelSkillCycle(unittest.TestCase):
    def _settings(self):
        return Settings(llm_api_key="", max_retries=0, memory_db=":memory:")

    def test_offline_brain_realizes_grid_blueprint(self):
        plan = OfflineBrain().decide({
            "source": "excel", "url": "/tmp/x.xlsx", "target": "/tmp/x.xlsx",
            "inventory": {"exists": False}, "stats": {"rows": 0},
            "blueprint": {"headers": ["a", "b"], "rows": [[1, None]],
                          "formulas": {"B2": "=A2*2"},
                          "format": {"target": "A1:B1", "bold": True}},
        }, "build the workbook")
        for action in plan.actions:
            action.validate()
        tools = [(a.tool, a.action) for a in plan.actions]
        self.assertEqual(tools[0], ("system", "report"))
        self.assertIn(("excel", "create"), tools)
        self.assertIn(("excel", "set_formula"), tools)
        self.assertIn(("excel", "format"), tools)
        self.assertEqual(tools[-1], ("excel", "save"))

    def test_agent_cycle_writes_real_xlsx(self):
        from jarvis import JarvisAgent
        from jarvis.skills.office import ExcelSkill

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "cycle.xlsx"
            skill = ExcelSkill(path=target, blueprint={
                "title": "Cycle Sheet", "sheet": "Data",
                "headers": ["k", "v", "calc"],
                "rows": [["alpha", 2, None], ["beta", 3, None]],
                "formulas": {"C2": "=B2*10", "C3": "=B3*10"},
                "format": {"target": "A1:C1", "bold": True},
            })
            with JarvisAgent(self._settings()) as agent:
                agent.register(skill)
                result = agent.run("excel")

            self.assertTrue(result.success, result.summary)
            self.assertTrue(target.exists())
            probe = ExcelModule(self._settings())
            probe.open(str(target))
            inv = probe.read(sheet="Data")
            self.assertEqual(inv["rows"][0], ["k", "v", "calc"])
            self.assertEqual(inv["formulas"]["C3"], "=B3*10")

    def test_agent_cycle_forced_dry_run_touches_nothing(self):
        from jarvis import JarvisAgent
        from jarvis.skills.office import ExcelSkill

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "shadow.xlsx"
            skill = ExcelSkill(path=target, blueprint={
                "headers": ["a"], "rows": [[1]],
            })
            with JarvisAgent(self._settings(), dry_run=True) as agent:
                agent.register(skill)
                result = agent.run("excel")

            self.assertTrue(result.success, result.summary)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
