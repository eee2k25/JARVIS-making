"""Long-term mission memory — 'a memory layer that learns from the past'.

A small SQLite store (the Honcho role from the nine-step map, self-hosted):
every completed mission is recorded — skill, outcome, summary, brain and
actions — and the most recent entries are fed back into the cognitive
pipeline as few-shot context, so the brain plans with knowledge of what
already worked (or failed) before.

The database lives at JARVIS_MEMORY_DB (default logs/memory/jarvis.db —
inside the gitignored logs/ tree). Pass ":memory:" for a throwaway store.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .config import Settings
from .logging_setup import get_logger

log = get_logger("jarvis.memory")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS missions (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    skill     TEXT    NOT NULL,
    mission   TEXT    NOT NULL,
    success   INTEGER NOT NULL,
    summary   TEXT    NOT NULL DEFAULT '',
    brain     TEXT    NOT NULL DEFAULT '',
    actions   TEXT    NOT NULL DEFAULT '[]',
    elapsed_s REAL    NOT NULL DEFAULT 0.0
)
"""


class MemoryStore:
    """Append-only mission history with snippet retrieval for the brain."""

    def __init__(self, db_path: str = ":memory:") -> None:
        self.db_path = db_path
        if db_path != ":memory:":
            Path(db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    @classmethod
    def from_settings(cls, settings: Settings) -> "MemoryStore":
        return cls(settings.memory_db or ":memory:")

    # ── writing ──────────────────────────────────────────────────────────
    def record(self, skill: str, mission: str, success: bool, summary: str,
               brain: str = "", actions: list[dict] | None = None,
               elapsed_s: float = 0.0) -> int:
        cur = self._conn.execute(
            "INSERT INTO missions (ts, skill, mission, success, summary, "
            "brain, actions, elapsed_s) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (time.time(), skill, mission, int(bool(success)), summary,
             brain, json.dumps(actions or [], default=str), float(elapsed_s)),
        )
        self._conn.commit()
        log.info("memory recorded: %s %s — %s", skill,
                 "SUCCESS" if success else "FAILURE", summary[:80])
        return int(cur.lastrowid or 0)

    # ── reading ──────────────────────────────────────────────────────────
    def recent(self, limit: int = 5) -> list[dict]:
        rows = self._conn.execute(
            "SELECT ts, skill, mission, success, summary, brain, actions, "
            "elapsed_s FROM missions ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            {"ts": r[0], "skill": r[1], "mission": r[2], "success": bool(r[3]),
             "summary": r[4], "brain": r[5],
             "actions": json.loads(r[6] or "[]"), "elapsed_s": r[7]}
            for r in rows
        ]

    def context_snippets(self, limit: int = 5) -> list[str]:
        """Compact past-mission lines for few-shot LLM context."""
        snippets = []
        for m in reversed(self.recent(limit)):  # oldest first
            stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(m["ts"]))
            outcome = "SUCCESS" if m["success"] else "FAILURE"
            snippets.append(f"[{stamp}] {m['skill']} -> {outcome}: "
                            f"{m['summary'][:120]}")
        return snippets

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM missions")
                   .fetchone()[0])

    def stats(self) -> dict:
        row = self._conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(success), 0) FROM missions"
        ).fetchone()
        total, wins = int(row[0]), int(row[1])
        return {"missions": total, "successes": wins,
                "failures": total - wins, "db": self.db_path}

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # pragma: no cover - sqlite teardown is best effort
            pass

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
