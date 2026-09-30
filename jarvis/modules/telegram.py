"""Telegram channel bridge — bot send + update polling, token-gated.

The Telegram leg of the nine-step map's 'connect my channels'. Real bot
traffic via api.telegram.org once JARVIS_TELEGRAM_BOT_TOKEN and
JARVIS_TELEGRAM_CHAT_ID are configured; shadow-mode notifications elsewhere.
"""

from __future__ import annotations

from ..exceptions import ActionError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.telegram")

_API = "https://api.telegram.org/bot{token}/{method}"


class TelegramModule(AutomationModule):
    name = "telegram"

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        s = self.settings
        missing = [name for name, val in (
            ("JARVIS_TELEGRAM_BOT_TOKEN", s.telegram_bot_token),
            ("JARVIS_TELEGRAM_CHAT_ID", s.telegram_chat_id),
        ) if not val]
        if missing:
            return Capability(self.name, False,
                              f"unconfigured ({', '.join(missing)} missing)")
        return Capability(self.name, True,
                          f"bot channel to chat {s.telegram_chat_id}")

    def _post(self, method: str, payload: dict) -> dict:
        self.require_real()
        import requests

        url = _API.format(token=self.settings.telegram_bot_token,
                          method=method)
        resp = requests.post(url, json=payload,
                             timeout=self.settings.http_timeout)
        if resp.status_code >= 400:
            raise ActionError(f"telegram.{method}: HTTP {resp.status_code}: "
                              f"{resp.text[:160]}")
        data = resp.json()
        if not data.get("ok"):
            raise ActionError(f"telegram.{method}: {data}")
        return data.get("result", {})

    # ── outbound ─────────────────────────────────────────────────────────
    def send(self, text: str) -> dict:
        """Deliver a message to the operator's Telegram chat."""
        if self.dry_run:
            return self.shadow("send", text=text[:120])
        if not text or not text.strip():
            raise ActionError("telegram.send: text must be non-empty")
        result = self._post("sendMessage", {
            "chat_id": self.settings.telegram_chat_id,
            "text": text,
        })
        return {"sent": True, "message_id": result.get("message_id"),
                "chat_id": self.settings.telegram_chat_id, "chars": len(text)}

    # ── inbound (one poll; a channel loop can call this repeatedly) ──────
    def updates(self, offset: int = 0, limit: int = 10) -> dict:
        if self.dry_run:
            return self.shadow("updates", offset=offset, limit=limit)
        result = self._post("getUpdates", {"offset": int(offset),
                                           "limit": int(limit)})
        messages = []
        for upd in result:
            msg = upd.get("message") or upd.get("edited_message") or {}
            messages.append({
                "update_id": upd.get("update_id"),
                "text": msg.get("text", ""),
                "from": (msg.get("from") or {}).get("username", ""),
            })
        return {"updates": messages, "count": len(messages),
                "next_offset": (messages[-1]["update_id"] + 1) if messages
                else int(offset)}
