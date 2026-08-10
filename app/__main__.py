from __future__ import annotations

import asyncio
import sys

from app.config import ConfigurationError, Settings


async def async_main(settings: Settings) -> None:
    from app.agent import create_agent
    from app.audio import Microphone, Speaker, describe_device
    from app.realtime import VoiceRuntime

    loop = asyncio.get_running_loop()
    input_name = describe_device(settings.input_device, kind="input")
    output_name = describe_device(settings.output_device, kind="output")
    print(
        "Realtime Voice Assistant\n"
        f"Model: {settings.model}\n"
        f"Voice: {settings.voice}\n"
        f"Input device: {input_name}\n"
        f"Output device: {output_name}\n"
        "\nYou can interrupt the assistant at any time.\n"
        "Press Ctrl+C to exit."
    )

    runtime = VoiceRuntime(settings, create_agent())
    tracker = runtime.playback_tracker
    queue_blocks = settings.microphone_queue_ms // settings.block_ms
    max_output_bytes = settings.sample_rate * 2 * settings.playback_buffer_ms // 1_000
    prefill_bytes = settings.sample_rate * 2 * settings.playback_prefill_ms // 1_000
    microphone: Microphone | None = None
    speaker: Speaker | None = None
    try:
        microphone = Microphone(
            loop=loop,
            sample_rate=settings.sample_rate,
            block_frames=settings.block_frames,
            queue_blocks=queue_blocks,
            device=settings.input_device,
        )
        speaker = Speaker(
            tracker=tracker,
            sample_rate=settings.sample_rate,
            block_frames=settings.block_frames,
            prefill_bytes=prefill_bytes,
            max_buffer_bytes=max_output_bytes,
            device=settings.output_device,
        )
        speaker.start()
        microphone.start()
        await runtime.run(microphone, speaker)
    finally:
        if microphone is not None:
            microphone.close()
        if speaker is not None:
            speaker.close()


def main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Import the native audio backend only after validating configuration. This keeps errors such
    # as a missing API key immediate even on machines with a broken PortAudio installation.
    import sounddevice as sd

    from app.audio import AudioDeviceError
    from app.realtime import RealtimeConnectionError

    try:
        asyncio.run(async_main(settings))
    except KeyboardInterrupt:
        print("\nDisconnected.")
        return 0
    except (AudioDeviceError, RealtimeConnectionError, sd.PortAudioError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
