"""Local fixture HTTP server — lets the full agent cycle run offline.

Serves assets/fixtures/ over 127.0.0.1 on an ephemeral port in a daemon
thread, so demos and tests never depend on external network access.
"""

from __future__ import annotations

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import project_root
from .logging_setup import get_logger

log = get_logger("jarvis.fixtures")


class _QuietHandler(SimpleHTTPRequestHandler):
    """Fixture handler without per-request stderr noise."""

    def log_message(self, *args, **kwargs) -> None:  # noqa: N802
        pass


class FixtureServer:
    """Tiny localhost server for bundled test pages."""

    def __init__(self, directory: str | Path | None = None,
                 host: str = "127.0.0.1", port: int = 0) -> None:
        root = Path(directory) if directory else project_root() / "assets" / "fixtures"
        handler = partial(_QuietHandler, directory=str(root))
        self._httpd = ThreadingHTTPServer((host, port), handler)
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}"

    def page(self, name: str = "control_panel.html") -> str:
        return f"{self.url}/{name}"

    def start(self) -> "FixtureServer":
        self._thread = threading.Thread(target=self._httpd.serve_forever,
                                        daemon=True, name="jarvis-fixture-httpd")
        self._thread.start()
        log.info("fixture server at %s", self.url)
        return self

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()

    def __enter__(self) -> "FixtureServer":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()
