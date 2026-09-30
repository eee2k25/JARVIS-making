"""Calendar automation — cross-platform ICS engine + upcoming-event queries.

The calendar tool from the nine-step map, built on the open iCalendar
standard: every event lives in a plain .ics file that Google/Apple/Outlook
calendars can import or export. Create a calendar, add events, list what is
upcoming — real everywhere Python runs, no cloud account required.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

from ..exceptions import ActionError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.calendar")


def _iso(value) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


class CalendarModule(AutomationModule):
    name = "calendar"

    def __init__(self, settings, dry_run_override: bool | None = None) -> None:
        super().__init__(settings, dry_run_override)
        self._cal = None
        self._path: Path | None = None

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        try:
            import icalendar  # noqa: F401
        except ImportError as exc:
            return Capability(self.name, False, f"missing dependency: {exc}")
        return Capability(self.name, True,
                          f"icalendar {getattr(icalendar, '__version__', '?')} "
                          f"ICS engine")

    def _ics(self):
        self.require_real()
        import icalendar

        return icalendar

    def _ensure_cal(self):
        if self._cal is None:
            ical = self._ics()
            cal = ical.Calendar()
            cal.add("prodid", "-//J.A.R.V.I.S.//Calendar Engine//EN")
            cal.add("version", "2.0")
            self._cal = cal
        return self._cal

    # ── lifecycle ────────────────────────────────────────────────────────
    def create(self, path: str | None = None) -> dict:
        if self.dry_run:
            return self.shadow("create", path=path)
        ical = self._ics()
        cal = ical.Calendar()
        cal.add("prodid", "-//J.A.R.V.I.S.//Calendar Engine//EN")
        cal.add("version", "2.0")
        self._cal = cal
        self._path = Path(path) if path else None
        return {"created": str(self._path) if self._path else "(unsaved)"}

    def open(self, path: str) -> dict:
        if self.dry_run:
            return self.shadow("open", path=path)
        p = Path(path).expanduser()
        if not p.exists():
            raise ActionError(f"calendar: file not found: {p}")
        ical = self._ics()
        self._cal = ical.Calendar.from_ical(p.read_bytes())
        self._path = p
        return {"opened": str(p), "events": len(self._events_raw())}

    def save(self, path: str | None = None) -> dict:
        if self.dry_run:
            return self.shadow("save", path=path)
        cal = self._ensure_cal()
        p = Path(path) if path else self._path
        if p is None:
            raise ActionError("calendar.save: no path given and none open")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(cal.to_ical())
        self._path = p
        log.info("saved %s (%d bytes)", p, p.stat().st_size)
        return {"saved": str(p), "bytes": p.stat().st_size,
                "events": len(self._events_raw())}

    # ── queries ──────────────────────────────────────────────────────────
    def _events_raw(self) -> list[dict]:
        cal = self._ensure_cal()
        out = []
        for comp in cal.walk("VEVENT"):
            start = comp.get("dtstart").dt if comp.get("dtstart") else None
            end = comp.get("dtend").dt if comp.get("dtend") else None
            out.append({
                "uid": str(comp.get("uid", "")),
                "title": str(comp.get("summary", "")),
                "start": start,
                "end": end,
                "location": str(comp.get("location", "")),
                "notes": str(comp.get("description", "")),
            })
        return out

    @staticmethod
    def _as_dt(value) -> datetime:
        if isinstance(value, datetime):
            return value if value.tzinfo else value
        return datetime(value.year, value.month, value.day)

    def events(self, start: str | None = None,
               end: str | None = None) -> dict:
        """List events, optionally within an ISO datetime window."""
        if self.dry_run:
            return self.shadow("events", start=start, end=end)
        lo = datetime.fromisoformat(start) if start else None
        hi = datetime.fromisoformat(end) if end else None
        picked = []
        for ev in self._events_raw():
            s = self._as_dt(ev["start"]) if ev["start"] else None
            if lo and s and s < lo:
                continue
            if hi and s and s > hi:
                continue
            picked.append({**ev, "start": _iso(ev["start"]),
                           "end": _iso(ev["end"])})
        picked.sort(key=lambda e: e["start"] or "")
        return {"events": picked, "count": len(picked),
                "path": str(self._path) if self._path else None}

    def upcoming(self, days: int = 7) -> dict:
        now = datetime.now()
        res = self.events(start=now.isoformat(),
                          end=(now + timedelta(days=max(1, int(days))))
                          .isoformat())
        if self.dry_run:
            return res
        return {"events": res["events"], "count": res["count"],
                "days": int(days), "path": res.get("path")}

    # ── editing ──────────────────────────────────────────────────────────
    def add_event(self, title: str, start: str, end: str | None = None,
                  location: str = "", notes: str = "") -> dict:
        if self.dry_run:
            return self.shadow("add_event", title=title, start=start, end=end,
                               location=location, notes=notes)
        if not title or not title.strip():
            raise ActionError("calendar.add_event: title is required")
        try:
            start_dt = (date.fromisoformat(start) if len(start) == 10
                        else datetime.fromisoformat(start))
            end_dt = (date.fromisoformat(end) if end and len(end) == 10
                      else datetime.fromisoformat(end) if end else None)
        except ValueError as exc:
            raise ActionError(
                f"calendar.add_event: bad ISO date/time {start!r}") from exc
        if end_dt is None:
            end_dt = (start_dt + timedelta(hours=1)
                      if isinstance(start_dt, datetime) else start_dt)
        if end_dt < start_dt:
            raise ActionError("calendar.add_event: end precedes start")

        ical = self._ics()
        ev = ical.Event()
        ev.add("summary", title.strip())
        ev.add("dtstart", start_dt)
        ev.add("dtend", end_dt)
        if location:
            ev.add("location", location)
        if notes:
            ev.add("description", notes)
        self._ensure_cal().add_component(ev)
        return {"added_event": title.strip(), "start": _iso(start_dt),
                "end": _iso(end_dt), "events": len(self._events_raw())}
