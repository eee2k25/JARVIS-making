"""Dynamic Browser Automation — Selenium WebDriver.

Stateful browser sessions for JavaScript-rendered DOMs: waits, dynamic
event triggers, session-cookie persistence, and JS execution. Degrades to
dry-run shadow mode when no browser binary exists (e.g. headless CI).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from ..config import Settings
from ..exceptions import ActionError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.browser")

_BROWSER_CANDIDATES = ("google-chrome", "google-chrome-stable", "chromium",
                       "chromium-browser", "chrome")


class BrowserModule(AutomationModule):
    name = "browser"

    def __init__(self, settings: Settings, dry_run_override: bool | None = None) -> None:
        super().__init__(settings, dry_run_override)
        self._driver: Any = None

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        try:
            import selenium  # noqa: F401
        except ImportError as exc:
            return Capability(self.name, False, f"missing dependency: {exc}")

        binary = self._resolve_binary()
        if binary:
            return Capability(self.name, True, f"chromium-family binary: {binary}")
        return Capability(
            self.name, False,
            "no chrome/chromium binary on PATH "
            "(Selenium Manager may still download one if network allows)",
        )

    def _resolve_binary(self) -> str | None:
        if self.settings.browser_binary:
            return self.settings.browser_binary
        found = shutil.which(_BROWSER_CANDIDATES[0])
        if found:
            return found
        for cand in _BROWSER_CANDIDATES[1:]:
            found = shutil.which(cand)
            if found:
                return found
        return None

    # ── session lifecycle ────────────────────────────────────────────────
    def start(self) -> Any:
        """Launch a (headless-by-default) Chrome session."""
        if self._driver is not None:
            return self._driver
        self.require_real()

        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        if self.settings.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--window-size=1440,900")
        opts.add_argument(f"--user-agent={self.settings.user_agent}")
        binary = self._resolve_binary()
        if binary:
            opts.binary_location = binary

        log.info("launching chrome (headless=%s)", self.settings.headless)
        self._driver = webdriver.Chrome(options=opts)
        if self.settings.implicit_wait:
            self._driver.implicitly_wait(self.settings.implicit_wait)
        return self._driver

    def quit(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:  # pragma: no cover
                pass
            self._driver = None
            log.info("browser session closed")

    def __enter__(self) -> "BrowserModule":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.quit()

    def _d(self) -> Any:
        if self._driver is None:
            self.start()
        return self._driver

    # ── navigation ───────────────────────────────────────────────────────
    def open(self, url: str) -> dict:
        if self.dry_run:
            return self.shadow("open", url=url)
        d = self._d()
        d.get(url)
        return {"url": d.current_url, "title": d.title}

    @property
    def current_url(self) -> str:
        if self.dry_run:
            return "dry-run://current"
        return self._d().current_url

    @property
    def title(self) -> str:
        if self.dry_run:
            return "(dry-run)"
        return self._d().title

    # ── element interaction ──────────────────────────────────────────────
    def _find(self, selector: str, timeout: float = 10.0):
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC

        d = self._d()
        return WebDriverWait(d, timeout).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
        )

    def click(self, selector: str, timeout: float = 10.0) -> dict:
        if self.dry_run:
            return self.shadow("click", selector=selector)
        el = self._find(selector, timeout)
        el.click()
        return {"clicked": selector}

    def type(self, selector: str, text: str, timeout: float = 10.0,
             clear: bool = True, secret: bool = False) -> dict:
        if self.dry_run:
            return self.shadow("type", selector=selector,
                               text="<redacted>" if secret else text)
        el = self._find(selector, timeout)
        if clear:
            el.clear()
        el.send_keys(text)
        return {"typed_into": selector, "chars": len(text)}

    def submit(self, selector: str = "form", timeout: float = 10.0) -> dict:
        if self.dry_run:
            return self.shadow("submit", selector=selector)
        form = self._find(selector, timeout)
        form.submit()
        return {"submitted": selector, "landed_on": self._d().current_url}

    def text_of(self, selector: str, timeout: float = 10.0) -> str:
        if self.dry_run:
            return "(dry-run text)"
        return self._find(selector, timeout).text

    # ── dynamic triggers ─────────────────────────────────────────────────
    def scroll(self, pixels: int = 800) -> dict:
        return self.execute_js(f"window.scrollBy(0, {pixels});")

    def execute_js(self, script: str, *args) -> dict:
        if self.dry_run:
            return self.shadow("execute_js", script=script[:120])
        result = self._d().execute_script(script, *args)
        return {"js_result": result}

    def wait_for(self, selector: str, timeout: float = 10.0) -> dict:
        if self.dry_run:
            return self.shadow("wait_for", selector=selector, timeout=timeout)
        self._find(selector, timeout)
        return {"appeared": selector}

    def screenshot(self, path: str | None = None) -> dict:
        if self.dry_run:
            return self.shadow("screenshot", path=path)
        target = Path(path or "logs/browser_shot.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        ok = self._d().save_screenshot(str(target))
        if not ok:
            raise ActionError(f"screenshot failed -> {target}")
        return {"screenshot": str(target)}

    # ── session state (cookies) ──────────────────────────────────────────
    def save_cookies(self, path: str = "logs/cookies.json") -> dict:
        if self.dry_run:
            return self.shadow("save_cookies", path=path)
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        cookies = self._d().get_cookies()
        p.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        return {"saved": len(cookies), "to": str(p)}

    def load_cookies(self, path: str = "logs/cookies.json") -> dict:
        if self.dry_run:
            return self.shadow("load_cookies", path=path)
        cookies = json.loads(Path(path).read_text(encoding="utf-8"))
        d = self._d()
        # cookies need a same-domain page loaded first
        if "about" in (d.current_url or ""):
            d.get("about:blank")
        for c in cookies:
            c.pop("expiry", None)  # selenium rejects millisecond expiry
            try:
                d.add_cookie(c)
            except Exception as exc:  # pragma: no cover
                log.warning("cookie %s rejected: %s", c.get("name"), exc)
        return {"loaded": len(cookies), "from": path}
