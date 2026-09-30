"""Email automation — IMAP inbox + SMTP send, credential-gated.

The email tool from the nine-step map. Real against any IMAP/SMTP provider
(Gmail app passwords, Fastmail, self-hosted…) once JARVIS_EMAIL_* settings
are configured; without them the module self-reports unavailable and every
action degrades to the standard dry-run shadow log.

Credentials are never logged — only connection targets and counts.
"""

from __future__ import annotations

from ..exceptions import ActionError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.email")


class EmailModule(AutomationModule):
    name = "email"

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        s = self.settings
        missing = [name for name, val in (
            ("JARVIS_EMAIL_ADDRESS", s.email_address),
            ("JARVIS_EMAIL_PASSWORD", s.email_password),
            ("JARVIS_EMAIL_IMAP_HOST", s.email_imap_host),
            ("JARVIS_EMAIL_SMTP_HOST", s.email_smtp_host),
        ) if not val]
        if missing:
            return Capability(self.name, False,
                              f"unconfigured ({', '.join(missing)} missing)")
        return Capability(self.name, True,
                          f"IMAP {s.email_imap_host} + SMTP {s.email_smtp_host} "
                          f"for {s.email_address}")

    # ── IMAP plumbing ────────────────────────────────────────────────────
    def _imap(self):
        self.require_real()
        import imaplib

        s = self.settings
        conn = imaplib.IMAP4_SSL(s.email_imap_host, s.email_imap_port)
        conn.login(s.email_address, s.email_password)
        conn.select(s.email_mailbox or "INBOX")
        return conn

    @staticmethod
    def _headers(data: list) -> dict:
        import email as email_lib
        from email.header import decode_header, make_header

        raw = data[0][1] if data and isinstance(data[0], tuple) else b""
        msg = email_lib.message_from_bytes(raw)

        def dec(field: str) -> str:
            return str(make_header(decode_header(msg.get(field, ""))))

        return {"from": dec("From"), "subject": dec("Subject"),
                "date": dec("Date")}

    def _fetch_recent(self, conn, criterion: str, limit: int) -> list[dict]:
        status, data = conn.uid("search", None, criterion)
        if status != "OK" or not data or not data[0]:
            return []
        uids = data[0].split()[-max(1, int(limit)):]
        messages = []
        for uid in reversed(uids):  # newest first
            status, fetched = conn.uid("fetch", uid,
                                       "(RFC822.HEADER RFC822.SIZE)")
            if status != "OK":
                continue
            info = self._headers(fetched)
            size = 0
            for part in fetched or []:
                if isinstance(part, tuple) and len(part) > 1 \
                        and isinstance(part[1], bytes):
                    size = max(size, len(part[1]))
            messages.append({"uid": uid.decode() if isinstance(uid, bytes)
                             else str(uid), **info, "size_bytes": size})
        return messages

    # ── reading ──────────────────────────────────────────────────────────
    def inbox(self, limit: int = 10) -> dict:
        if self.dry_run:
            return self.shadow("inbox", limit=limit)
        conn = self._imap()
        try:
            messages = self._fetch_recent(conn, "ALL", limit)
        finally:
            try:
                conn.logout()
            except Exception:  # pragma: no cover
                pass
        log.info("inbox fetched: %d message(s)", len(messages))
        return {"messages": messages, "count": len(messages),
                "mailbox": self.settings.email_mailbox or "INBOX"}

    def search(self, query: str, limit: int = 10) -> dict:
        if self.dry_run:
            return self.shadow("search", query=query, limit=limit)
        clean = (query or "").replace('"', "").strip()
        if not clean:
            raise ActionError("email.search: query must be non-empty")
        conn = self._imap()
        try:
            messages = self._fetch_recent(conn, f'TEXT "{clean}"', limit)
        finally:
            try:
                conn.logout()
            except Exception:  # pragma: no cover
                pass
        return {"messages": messages, "count": len(messages), "query": clean}

    def read(self, uid: str) -> dict:
        if self.dry_run:
            return self.shadow("read", uid=uid)
        conn = self._imap()
        try:
            status, fetched = conn.uid("fetch", str(uid).encode(), "(RFC822)")
            if status != "OK" or not fetched or not isinstance(fetched[0], tuple):
                raise ActionError(f"email.read: message {uid} not found")
            import email as email_lib

            msg = email_lib.message_from_bytes(fetched[0][1])
            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(
                            part.get_content_charset() or "utf-8", "replace")
                        break
            else:
                body = (msg.get_payload(decode=True) or b"").decode(
                    msg.get_content_charset() or "utf-8", "replace")
        finally:
            try:
                conn.logout()
            except Exception:  # pragma: no cover
                pass
        info = {"from": str(msg.get("From", "")),
                "subject": str(msg.get("Subject", "")),
                "date": str(msg.get("Date", ""))}
        return {"uid": str(uid), **info, "body": body[:4000],
                "chars": len(body)}

    # ── sending ──────────────────────────────────────────────────────────
    def send(self, to: str, subject: str, body: str) -> dict:
        if self.dry_run:
            return self.shadow("send", to=to, subject=subject,
                               body_chars=len(body or ""))
        if not to or "@" not in to:
            raise ActionError("email.send: a recipient address is required")
        import smtplib
        from email.message import EmailMessage

        s = self.settings
        msg = EmailMessage()
        msg["From"] = s.email_address
        msg["To"] = to
        msg["Subject"] = subject or "(no subject)"
        msg.set_content(body or "")
        with smtplib.SMTP(s.email_smtp_host, s.email_smtp_port) as smtp:
            smtp.starttls()
            smtp.login(s.email_address, s.email_password)
            smtp.send_message(msg)
        log.info("email sent to %s: %s", to, (subject or "")[:60])
        return {"sent": True, "to": to, "subject": msg["Subject"]}
