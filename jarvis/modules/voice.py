"""Voice I/O — ElevenLabs text-to-speech + speech-to-text, shadow-first.

The voice layer from the nine-step map: give the agent a voice so you can
literally talk to it. Real synthesis runs through the ElevenLabs REST API
when JARVIS_ELEVENLABS_API_KEY is configured (any voice, British ones very
much included); without a key the module self-reports unavailable and speak /
transcribe degrade to the standard dry-run shadow log.

speak(text)      -> logs/voice/<stamp>.mp3   (real audio when configured)
transcribe(path) -> text from an audio file  (ElevenLabs Scribe when configured)
"""

from __future__ import annotations

import time
from pathlib import Path

from ..exceptions import ActionError
from ..logging_setup import get_logger
from .base import AutomationModule, Capability

log = get_logger("jarvis.voice")

_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"


class VoiceModule(AutomationModule):
    name = "voice"

    # ── capability ───────────────────────────────────────────────────────
    def check_capability(self) -> Capability:
        key = self.settings.elevenlabs_api_key
        if not key:
            return Capability(self.name, False,
                              "no JARVIS_ELEVENLABS_API_KEY — shadow mode")
        return Capability(self.name, True,
                          f"ElevenLabs TTS (voice_id={self.settings.voice_id}, "
                          f"model={self.settings.voice_model})")

    def _headers(self) -> dict:
        self.require_real()
        return {"xi-api-key": self.settings.elevenlabs_api_key,
                "Content-Type": "application/json"}

    def _output_dir(self) -> Path:
        return Path(self.settings.voice_output_dir or "logs/voice")

    # ── text to speech ───────────────────────────────────────────────────
    def speak(self, text: str, voice_id: str | None = None,
              path: str | None = None) -> dict:
        """Synthesize speech and persist the audio artifact."""
        if not text or not text.strip():
            raise ActionError("voice.speak: text must be non-empty")
        if self.dry_run:
            return self.shadow("speak", text=text[:120],
                               voice_id=voice_id or self.settings.voice_id)
        import requests

        out = Path(path) if path else self._output_dir() / (
            f"speech_{time.strftime('%Y%m%d_%H%M%S')}.mp3")
        out.parent.mkdir(parents=True, exist_ok=True)
        url = _TTS_URL.format(voice_id=voice_id or self.settings.voice_id)
        resp = requests.post(
            url,
            headers=self._headers(),
            json={"text": text, "model_id": self.settings.voice_model},
            timeout=self.settings.http_timeout,
        )
        if resp.status_code >= 400:
            raise ActionError(f"voice.speak: ElevenLabs returned "
                              f"HTTP {resp.status_code}: {resp.text[:160]}")
        out.write_bytes(resp.content)
        log.info("speech synthesized: %s (%d bytes)", out, len(resp.content))
        return {"spoken": text[:160], "audio": str(out),
                "bytes": len(resp.content),
                "voice_id": voice_id or self.settings.voice_id}

    # ── speech to text ───────────────────────────────────────────────────
    def transcribe(self, path: str) -> dict:
        """Speech -> text via ElevenLabs Scribe (for talk-to-it channels)."""
        audio = Path(path).expanduser()
        if self.dry_run:
            return self.shadow("transcribe", path=path)
        if not audio.exists():
            raise ActionError(f"voice.transcribe: audio not found: {audio}")
        import requests

        resp = requests.post(
            _STT_URL,
            headers={"xi-api-key": self.settings.elevenlabs_api_key},
            files={"file": (audio.name, audio.read_bytes())},
            data={"model_id": "scribe_v1"},
            timeout=self.settings.http_timeout,
        )
        if resp.status_code >= 400:
            raise ActionError(f"voice.transcribe: ElevenLabs returned "
                              f"HTTP {resp.status_code}: {resp.text[:160]}")
        text = (resp.json() or {}).get("text", "")
        return {"transcribed": text, "audio": str(audio), "chars": len(text)}
