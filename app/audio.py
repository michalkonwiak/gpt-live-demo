from __future__ import annotations

import asyncio
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any

import sounddevice as sd
from agents.realtime.config import RealtimeAudioFormat
from agents.realtime.model import RealtimePlaybackState, RealtimePlaybackTracker


class AudioDeviceError(RuntimeError):
    """Raised when a local audio stream cannot be opened."""


class PlaybackBufferError(RuntimeError):
    """Raised instead of silently losing generated speech."""


@dataclass(slots=True)
class PlaybackChunk:
    data: memoryview
    item_id: str
    content_index: int
    offset: int = 0


class ThreadSafePlaybackTracker(RealtimePlaybackTracker):
    """SDK tracker protected because PortAudio and the SDK use different threads."""

    def __init__(self) -> None:
        super().__init__()
        self._tracker_lock = threading.RLock()

    def on_play_bytes(
        self, item_id: str, item_content_index: int, bytes: bytes
    ) -> None:
        with self._tracker_lock:
            super().on_play_bytes(item_id, item_content_index, bytes)

    def on_play_ms(self, item_id: str, item_content_index: int, ms: float) -> None:
        with self._tracker_lock:
            super().on_play_ms(item_id, item_content_index, ms)

    def on_interrupted(self) -> None:
        with self._tracker_lock:
            super().on_interrupted()

    def set_audio_format(self, format: RealtimeAudioFormat) -> None:
        with self._tracker_lock:
            super().set_audio_format(format)

    def get_state(self) -> RealtimePlaybackState:
        with self._tracker_lock:
            return super().get_state()


class Microphone:
    def __init__(
        self,
        *,
        loop: asyncio.AbstractEventLoop,
        sample_rate: int,
        block_frames: int,
        queue_blocks: int,
        device: str | int | None,
    ) -> None:
        self._loop = loop
        self._queue_blocks = queue_blocks
        self._chunks: deque[bytes] = deque()
        self._lock = threading.Lock()
        self._available = asyncio.Event()
        self._stream = sd.RawInputStream(
            samplerate=sample_rate,
            blocksize=block_frames,
            device=device,
            channels=1,
            dtype="int16",
            callback=self._callback,
        )

    def _callback(
        self, indata: memoryview, _frames: int, _time: Any, _status: Any
    ) -> None:
        chunk = bytes(indata)
        with self._lock:
            should_notify = not self._chunks
            if len(self._chunks) == self._queue_blocks:
                # Fresh microphone audio matters most for latency; discard the oldest unsent block.
                self._chunks.popleft()
            self._chunks.append(chunk)
        if should_notify:
            self._loop.call_soon_threadsafe(self._available.set)

    async def read(self) -> bytes:
        while True:
            with self._lock:
                if self._chunks:
                    return self._chunks.popleft()
                self._available.clear()
            await self._available.wait()

    def start(self) -> None:
        try:
            self._stream.start()
        except sd.PortAudioError as exc:
            raise AudioDeviceError(f"Nie można uruchomić mikrofonu: {exc}") from exc

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
        with self._lock:
            self._chunks.clear()


class Speaker:
    def __init__(
        self,
        *,
        tracker: ThreadSafePlaybackTracker,
        sample_rate: int,
        block_frames: int,
        prefill_bytes: int,
        max_buffer_bytes: int,
        device: str | int | None,
    ) -> None:
        self._tracker = tracker
        self._max_buffer_bytes = max_buffer_bytes
        self._prefill_bytes = prefill_bytes
        self._bytes_per_ms = sample_rate * 2 / 1_000
        self._silence = bytes(block_frames * 2)
        self._chunks: deque[PlaybackChunk] = deque()
        self._buffered_bytes = 0
        self._primed = False
        self._lock = threading.Lock()
        self._stream = sd.RawOutputStream(
            samplerate=sample_rate,
            blocksize=block_frames,
            device=device,
            channels=1,
            dtype="int16",
            callback=self._callback,
            latency="low",
        )

    def start(self) -> None:
        try:
            self._stream.start()
        except sd.PortAudioError as exc:
            raise AudioDeviceError(f"Nie można uruchomić głośnika: {exc}") from exc

    def enqueue(self, data: bytes, item_id: str, content_index: int) -> None:
        with self._lock:
            if self._buffered_bytes + len(data) > self._max_buffer_bytes:
                raise PlaybackBufferError(
                    "Bufor odtwarzania osiągnął bezpieczny limit; audio nie zostało odrzucone "
                    "po cichu. Sprawdź urządzenie wyjściowe lub zwiększ playback_buffer_ms."
                )
            self._chunks.append(PlaybackChunk(memoryview(data), item_id, content_index))
            self._buffered_bytes += len(data)
            if self._buffered_bytes >= self._prefill_bytes:
                self._primed = True

    def finish_response(self) -> None:
        """Release a short response that never reached the jitter-buffer target."""
        with self._lock:
            if self._chunks:
                self._primed = True

    def interrupt(self) -> None:
        # Locking against the callback makes clearing atomic at a PortAudio block boundary.
        with self._lock:
            self._chunks.clear()
            self._buffered_bytes = 0
            self._primed = False

    def _callback(
        self, outdata: memoryview, _frames: int, _time: Any, _status: Any
    ) -> None:
        output = memoryview(outdata).cast("B")
        output[:] = self._silence[: len(output)]
        written = 0
        played: list[tuple[str, int, int]] = []
        with self._lock:
            if not self._primed:
                return
            while written < len(output) and self._chunks:
                chunk = self._chunks[0]
                count = min(len(output) - written, len(chunk.data) - chunk.offset)
                part = chunk.data[chunk.offset : chunk.offset + count]
                output[written : written + count] = part
                if played and played[-1][:2] == (chunk.item_id, chunk.content_index):
                    previous_item_id, previous_index, previous_count = played[-1]
                    played[-1] = (previous_item_id, previous_index, previous_count + count)
                else:
                    played.append((chunk.item_id, chunk.content_index, count))
                chunk.offset += count
                written += count
                self._buffered_bytes -= count
                if chunk.offset == len(chunk.data):
                    self._chunks.popleft()
            if not self._chunks:
                self._primed = False
        # Report one duration per contiguous item, without allocating copies in the audio callback.
        for item_id, content_index, byte_count in played:
            self._tracker.on_play_ms(item_id, content_index, byte_count / self._bytes_per_ms)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()
        self.interrupt()


def describe_device(device: str | int | None, *, kind: str) -> str:
    try:
        resolved = sd.query_devices(device, kind=kind)
    except (sd.PortAudioError, ValueError) as exc:
        raise AudioDeviceError(f"Nie znaleziono urządzenia audio ({kind}): {exc}") from exc
    return str(resolved["name"])
