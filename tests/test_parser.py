"""Unit tests: parser DOM-traversal engine against embedded fixture HTML."""

from __future__ import annotations

import unittest

from jarvis.modules.parser import ParserModule

HTML = """
<html><head><title>Fixture Page</title></head><body>
  <h1>Main Title</h1><h2>Section</h2>
  <a href="/rel">Relative</a><a href="https://ext.example/x">External</a>
  <table><tr><th>k</th><th>v</th></tr><tr><td>reactor</td><td>3.1 GW</td></tr></table>
  <form method="post" action="/login">
    <input name="user" type="text" required>
    <input name="pw" type="password">
    <button>go</button>
  </form>
  <div class="score">42</div>
</body></html>
"""


class TestParser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parser = ParserModule(SettingsStub())
        cls.soup = ParserModule.parse_html(HTML)

    def test_title(self):
        self.assertEqual(ParserModule.title(self.soup), "Fixture Page")

    def test_headings(self):
        hs = ParserModule.headings(self.soup)
        self.assertEqual([h["level"] for h in hs], ["H1", "H2"])

    def test_links(self):
        links = ParserModule.find_links(self.soup, base_url="http://f.local/page")
        texts = [l["text"] for l in links]
        self.assertIn("Relative", texts)
        rel = next(l for l in links if l["text"] == "Relative")
        self.assertEqual(rel["href"], "http://f.local/rel")

    def test_tables(self):
        tables = ParserModule.find_tables(self.soup)
        self.assertEqual(tables[0][1], ["reactor", "3.1 GW"])

    def test_forms(self):
        forms = ParserModule.find_forms(self.soup)
        self.assertEqual(forms[0]["method"], "post")
        names = [f["name"] for f in forms[0]["fields"]]
        self.assertEqual(names, ["user", "pw"])

    def test_css_extract(self):
        got = ParserModule.extract(self.soup, {"score": ".score"})
        self.assertEqual(got["score"], ["42"])


class SettingsStub:
    http_timeout = 5
    user_agent = "test-agent"


if __name__ == "__main__":
    unittest.main()
