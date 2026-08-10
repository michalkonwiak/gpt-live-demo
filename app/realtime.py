from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import NoReturn

from agents.realtime import RealtimeAgent, RealtimeRunner, RealtimeSession

from app.audio import Microphone, Speaker, ThreadSafePlaybackTracker
from app.config import Settings


class RealtimeConnectionError(RuntimeError):
    """Raised for a fatal Realtime session error."""


class VoiceRuntime:
    def __init__(
        self,
        settings: Settings,
        agent: RealtimeAgent,
        log: Callable[[str], None] = print,
    ) -> None:
        self._settings = settings
        self._log = log
        self._tracker = ThreadSafePlaybackTracker()
        self._runner = RealtimeRunner(
            starting_agent=agent,
            config={
                "model_settings": {
                    "model_name": settings.model,
                    "output_modalities": ["audio"],
                    "audio": {
                        "input": {
                            "format": "pcm16",
                            "noise_reduction": {"type": "near_field"},
                            "transcription": {"model": "gpt-4o-mini-transcribe"},
                            "turn_detection": {
                                "type": "semantic_vad",
                                "eagerness": "medium",
                                "create_response": True,
                                "interrupt_response": True,
                            },
                        },
                        "output": {"format": "pcm16", "voice": settings.voice},
                    },
                    "reasoning": {"effort": "low"},
                }
            },
        )

    @property
    def playback_tracker(self) -> ThreadSafePlaybackTracker:
        return self._tracker

    async def run(self, microphone: Microphone, speaker: Speaker) -> NoReturn:
        session = await self._runner.run(
            model_config={"api_key": self._settings.api_key, "playback_tracker": self._tracker}
        )
        async with session:
            self._log("\nConnected.\n\nSpeak normally.")
            try:
                async with asyncio.TaskGroup() as tasks:
                    tasks.create_task(
                        self._send_microphone(session, microphone), name="microphone-send"
                    )
                    tasks.create_task(
                        self._receive_events(session, speaker), name="realtime-events"
                    )
            except* Exception as exc_group:
                first_error = exc_group.exceptions[0]
                raise RealtimeConnectionError(
                    f"Sesja Realtime przerwana: {first_error}"
                ) from first_error
        raise RealtimeConnectionError("Połączenie Realtime zostało zamknięte.")

    async def _send_microphone(
        self, session: RealtimeSession, microphone: Microphone
    ) -> NoReturn:
        while True:
            await session.send_audio(await microphone.read())

    async def _receive_events(self, session: RealtimeSession, speaker: Speaker) -> None:
        async for event in session:
            if event.type == "audio":
                speaker.enqueue(event.audio.data, event.item_id, event.content_index)
            elif event.type == "audio_interrupted":
                # The SDK reads the tracker before emitting this event and truncates server history.
                speaker.interrupt()
                if self._settings.debug:
                    self._log("[AI] interrupted")
            elif event.type == "audio_end":
                speaker.finish_response()
                if self._settings.debug:
                    self._log("[AI] response audio finished")
            elif event.type == "error":
                raise RealtimeConnectionError(f"Błąd OpenAI Realtime: {event.error}")
            elif event.type == "raw_model_event":
                self._handle_raw_event(event.data)

    def _handle_raw_event(self, event: object) -> None:
        if not self._settings.debug:
            return
        event_type = getattr(event, "type", "")
        if event_type == "input_audio_transcription_completed":
            self._log(f"USER: {getattr(event, 'transcript', '')}")
        elif event_type == "turn_started":
            self._log("[AI] response started")
        elif event_type == "turn_ended":
            self._log("[AI] response finished")
