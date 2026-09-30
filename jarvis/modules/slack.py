"""Slack channel bridge — incoming-webhook send, URL-gated.

The Slack leg of the nine-step map's 'connect my channels'. Real posts
through a Slack incoming webhook once JARVIS_SLACK_WEBHOOK_URL is set;
shadow-mode notifications elsewhere.
"""

from __future__ import annotations

from ..exceptions import ActionError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.slack")


class SlackModule(AutomationModule):
    name = "slack"

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        url = self.settings.slack_webhook_url
        if not url:
            return Capability(self.name, False,
                              "unconfigured (JARVIS_SLACK_WEBHOOK_URL missing)")
        return Capability(self.name, True, "incoming webhook configured")

    # ── outbound ─────────────────────────────────────────────────────────
    def send(self, text: str, channel: str | None = None) -> dict:
        """Post a message through the incoming webhook."""
        if self.dry_run:
            return self.shadow("send", text=text[:120], channel=channel)
        if not text or not text.strip():
            raise ActionError("slack.send: text must be non-empty")
        import requests

        payload = {"text": text}
        if channel:
            payload["channel"] = channel
        resp = requests.post(self.settings.slack_webhook_url, json=payload,
                             timeout=self.settings.http_timeout)
        if resp.status_code >= 400:
            raise ActionError(f"slack.send: HTTP {resp.status_code}: "
                              f"{resp.text[:160]}")
        log.info("slack message posted (%d chars)", len(text))
        return {"sent": True, "chars": len(text), "channel": channel or "(webhook default)"}
