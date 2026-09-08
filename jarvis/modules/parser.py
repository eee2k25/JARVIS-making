"""Data Ingestion & Parsing Engine — requests + BeautifulSoup4.

Headless HTTP fetch with polite defaults, then robust DOM traversal helpers
that compile structured data out of static HTML documents.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import requests
from bs4 import BeautifulSoup

from ..config import Settings
from ..exceptions import PerceptionError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.parser")


@dataclass
class ParseResult:
    """Container for one fetched document + its parsed DOM."""

    url: str
    status_code: int
    soup: BeautifulSoup
    elapsed_ms: float
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 400

    @property
    def text(self) -> str:
        return self.soup.get_text("\n", strip=True)


class ParserModule(AutomationModule):
    """Available anywhere Python runs; only needs network for remote URLs."""

    name = "parser"

    def __init__(self, settings: Settings, dry_run_override: bool | None = None) -> None:
        super().__init__(settings, dry_run_override)
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": settings.user_agent,
            "Accept-Language": "en-US,en;q=0.9",
        })

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        try:
            import bs4  # noqa: F401
            import requests  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            return Capability(self.name, False, f"missing dependency: {exc}")
        return Capability(self.name, True,
                          f"requests {requests.__version__} + bs4 {bs4.__version__}")

    # ── fetch ────────────────────────────────────────────────────────────
    def get(self, url: str, *, params: dict | None = None,
            headers: dict | None = None, retries: int = 2) -> ParseResult:
        """Fetch a document and return its parsed DOM. Raises PerceptionError
        on transport failure after small retry budget."""
        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                start = time.perf_counter()
                resp = self.session.get(
                    url, params=params, headers=headers,
                    timeout=self.settings.http_timeout,
                )
                elapsed = (time.perf_counter() - start) * 1000
                soup = BeautifulSoup(resp.text, "lxml" if self._has_lxml() else "html.parser")
                self._last_soup = soup  # cached for parser.extract follow-ups
                log.info("GET %s -> %s (%d bytes, %.0f ms)",
                         url, resp.status_code, len(resp.content), elapsed)
                return ParseResult(
                    url=str(resp.url), status_code=resp.status_code, soup=soup,
                    elapsed_ms=elapsed, headers=dict(resp.headers),
                )
            except requests.RequestException as exc:
                last_exc = exc
                log.warning("GET %s attempt %d/%d failed: %s",
                            url, attempt + 1, retries + 1, exc)
                time.sleep(0.4 * (attempt + 1))
        raise PerceptionError(f"failed to fetch {url}: {last_exc}") from last_exc

    # ── DOM traversal / extraction ───────────────────────────────────────
    @staticmethod
    def _has_lxml() -> bool:
        try:
            import lxml  # noqa: F401
            return True
        except ImportError:  # pragma: no cover
            return False

    @staticmethod
    def title(soup: BeautifulSoup) -> str:
        return (soup.title.string or "").strip() if soup.title else ""

    @staticmethod
    def extract(soup: BeautifulSoup, selectors: dict[str, str]) -> dict[str, list[str]]:
        """CSS-selector batch extraction: {field: css} -> {field: [texts]}."""
        out: dict[str, list[str]] = {}
        for key, css in selectors.items():
            out[key] = [el.get_text(strip=True) for el in soup.select(css)]
        return out

    @staticmethod
    def find_links(soup: BeautifulSoup, base_url: str = "") -> list[dict[str, str]]:
        """All hyperlinks as [{text, href}] (resolved when base_url given)."""
        from urllib.parse import urljoin

        links = []
        for a in soup.find_all("a", href=True):
            href = urljoin(base_url, a["href"]) if base_url else a["href"]
            links.append({"text": a.get_text(strip=True), "href": href})
        return links

    @staticmethod
    def find_tables(soup: BeautifulSoup) -> list[list[list[str]]]:
        """Every <table> as a list of rows of cell strings."""
        tables = []
        for table in soup.find_all("table"):
            rows = []
            for tr in table.find_all("tr"):
                cells = [c.get_text(strip=True)
                         for c in tr.find_all(["th", "td"])]
                if cells:
                    rows.append(cells)
            tables.append(rows)
        return tables

    @staticmethod
    def find_forms(soup: BeautifulSoup) -> list[dict[str, Any]]:
        """Forms as actionable dicts: method, action, and field inventory."""
        forms = []
        for form in soup.find_all("form"):
            fields = []
            for inp in form.find_all(["input", "textarea", "select"]):
                fields.append({
                    "name": inp.get("name", ""),
                    "type": inp.get("type", inp.name),
                    "placeholder": inp.get("placeholder", ""),
                    "required": inp.has_attr("required"),
                })
            forms.append({
                "method": (form.get("method") or "get").lower(),
                "action": form.get("action", ""),
                "fields": fields,
            })
        return forms

    @staticmethod
    def headings(soup: BeautifulSoup) -> list[dict[str, str]]:
        return [{"level": h.name.upper(), "text": h.get_text(strip=True)}
                for h in soup.find_all(["h1", "h2", "h3"])]

    @staticmethod
    def parse_html(html: str) -> BeautifulSoup:
        return BeautifulSoup(html, "lxml" if ParserModule._has_lxml() else "html.parser")
