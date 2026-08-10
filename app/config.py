from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigurationError(ValueError):
    """Raised when required application configuration is missing or invalid."""


def _optional_device(value: str | None) -> str | int | None:
    if value is None or not value.strip():
        return None
    normalized = value.strip()
    try:
        return int(normalized)
    except ValueError:
        return normalized


def _boolean(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    api_key: str
    model: str = "gpt-realtime-2.1"
    voice: str = "marin"
    input_device: str | int | None = None
    output_device: str | int | None = None
    debug: bool = False
    sample_rate: int = 24_000
    block_ms: int = 20
    microphone_queue_ms: int = 500
    playback_prefill_ms: int = 60
    # Realtime can generate substantially faster than wall-clock playback. This remains bounded
    # (~2.9 MiB of mono PCM16), while holding a complete normal spoken response without data loss.
    playback_buffer_ms: int = 60_000

    @property
    def block_frames(self) -> int:
        return self.sample_rate * self.block_ms // 1_000

    @classmethod
    def from_env(cls) -> Settings:
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise ConfigurationError(
                "Brak OPENAI_API_KEY. Skopiuj .env.example do .env i wpisz klucz API."
            )
        return cls(
            api_key=api_key,
            model=os.getenv("OPENAI_REALTIME_MODEL", "gpt-realtime-2.1").strip(),
            voice=os.getenv("OPENAI_REALTIME_VOICE", "marin").strip(),
            input_device=_optional_device(os.getenv("AUDIO_INPUT_DEVICE")),
            output_device=_optional_device(os.getenv("AUDIO_OUTPUT_DEVICE")),
            debug=_boolean(os.getenv("VOICE_DEBUG")),
        )
