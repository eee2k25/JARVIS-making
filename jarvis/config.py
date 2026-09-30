"""Central, environment-driven configuration.

All knobs come from environment variables (optionally a `.env` file) so the
same codebase runs unchanged on a headless CI box and on a desktop rig.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional dependency — config still works without it
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


@dataclass(frozen=True)
class Settings:
    # --- Cognitive pipeline (any OpenAI-compatible REST endpoint) ---
    llm_base_url: str = field(default_factory=lambda: _env(
        "JARVIS_LLM_BASE_URL", "https://api.openai.com/v1"))
    llm_api_key: str = field(default_factory=lambda: _env("JARVIS_LLM_API_KEY"))
    llm_model: str = field(default_factory=lambda: _env("JARVIS_LLM_MODEL", "gpt-4o-mini"))
    llm_timeout: float = field(default_factory=lambda: float(_env("JARVIS_LLM_TIMEOUT", "30")))

    # --- Data ingestion ---
    http_timeout: float = field(default_factory=lambda: float(_env("JARVIS_HTTP_TIMEOUT", "15")))
    user_agent: str = field(default_factory=lambda: _env(
        "JARVIS_USER_AGENT", "JARVIS-Agent/0.1 (+educational automation)"))

    # --- Dynamic browser automation ---
    headless: bool = field(default_factory=lambda: _env("JARVIS_HEADLESS", "true").lower() != "false")
    browser_binary: str = field(default_factory=lambda: _env("JARVIS_BROWSER_BINARY"))
    implicit_wait: float = field(default_factory=lambda: float(_env("JARVIS_IMPLICIT_WAIT", "0")))

    # --- State machine / resilience ---
    max_retries: int = field(default_factory=lambda: int(_env("JARVIS_MAX_RETRIES", "3")))
    backoff_base: float = field(default_factory=lambda: float(_env("JARVIS_BACKOFF_BASE", "1.5")))
    backoff_jitter: bool = field(default_factory=lambda: _env("JARVIS_BACKOFF_JITTER", "true").lower() != "false")

    # --- Operations ---
    dry_run: str = field(default_factory=lambda: _env("JARVIS_DRY_RUN", "auto"))  # auto|true|false
    log_level: str = field(default_factory=lambda: _env("JARVIS_LOG_LEVEL", "INFO"))
    log_file: str = field(default_factory=lambda: _env("JARVIS_LOG_FILE", ""))

    # --- GUI failsafe (PyAutoGUI) ---
    gui_failsafe: bool = field(default_factory=lambda: _env("JARVIS_GUI_FAILSAFE", "true").lower() != "false")
    gui_pause: float = field(default_factory=lambda: float(_env("JARVIS_GUI_PAUSE", "0.1")))

    # --- MS Office automation (Word / PowerPoint / Excel) ---
    office_output_dir: str = field(default_factory=lambda: _env(
        "JARVIS_OFFICE_OUTPUT_DIR", "logs/office"))

    # --- Operator identity (step 4: 'teach it who I am') ---
    operator_profile: str = field(default_factory=lambda: _env(
        "JARVIS_OPERATOR_PROFILE"))  # default: assets/profile/operator.md

    # --- Long-term memory (step 5: mission history for few-shot context) ---
    memory_db: str = field(default_factory=lambda: _env(
        "JARVIS_MEMORY_DB", "logs/memory/jarvis.db"))  # ":memory:" disables disk

    # --- Voice I/O (step 8: ElevenLabs TTS/STT) ---
    elevenlabs_api_key: str = field(default_factory=lambda: _env(
        "JARVIS_ELEVENLABS_API_KEY"))
    voice_id: str = field(default_factory=lambda: _env(
        "JARVIS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"))  # ElevenLabs default voice
    voice_model: str = field(default_factory=lambda: _env(
        "JARVIS_VOICE_MODEL", "eleven_multilingual_v2"))
    voice_output_dir: str = field(default_factory=lambda: _env(
        "JARVIS_VOICE_OUTPUT_DIR", "logs/voice"))

    # --- Email tool (step 7: IMAP/SMTP) ---
    email_address: str = field(default_factory=lambda: _env("JARVIS_EMAIL_ADDRESS"))
    email_password: str = field(default_factory=lambda: _env("JARVIS_EMAIL_PASSWORD"))
    email_imap_host: str = field(default_factory=lambda: _env("JARVIS_EMAIL_IMAP_HOST"))
    email_imap_port: int = field(default_factory=lambda: int(_env("JARVIS_EMAIL_IMAP_PORT", "993")))
    email_smtp_host: str = field(default_factory=lambda: _env("JARVIS_EMAIL_SMTP_HOST"))
    email_smtp_port: int = field(default_factory=lambda: int(_env("JARVIS_EMAIL_SMTP_PORT", "587")))
    email_mailbox: str = field(default_factory=lambda: _env("JARVIS_EMAIL_MAILBOX", "INBOX"))

    # --- Channels (step 8: Telegram / Slack) ---
    telegram_bot_token: str = field(default_factory=lambda: _env("JARVIS_TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _env("JARVIS_TELEGRAM_CHAT_ID"))
    slack_webhook_url: str = field(default_factory=lambda: _env("JARVIS_SLACK_WEBHOOK_URL"))

    # --- Dashboard (step 9: the Jarvis look) ---
    dashboard_host: str = field(default_factory=lambda: _env("JARVIS_DASHBOARD_HOST", "0.0.0.0"))
    dashboard_port: int = field(default_factory=lambda: int(_env("JARVIS_DASHBOARD_PORT", "8787")))

    @property
    def force_dry_run(self) -> bool:
        """true/false explicit; 'auto' lets each module decide by capability."""
        if self.dry_run.lower() == "true":
            return True
        return False

    @classmethod
    def load(cls) -> "Settings":
        return cls()


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent
