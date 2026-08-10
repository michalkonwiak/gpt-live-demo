# Local Realtime Voice Agent

Lokalny, pełnodupleksowy agent speech-to-speech. Jedna długotrwała sesja
`RealtimeRunner`/WebSocket przesyła PCM z mikrofonu bezpośrednio do OpenAI Realtime API i
streamuje PCM odpowiedzi do głośnika. Transkrypcja służy wyłącznie opcjonalnym logom — nie jest
wejściem osobnego pipeline'u STT → LLM → TTS.

## Requirements

- Python 3.13
- [uv](https://docs.astral.sh/uv/)
- konto OpenAI z dostępem do Realtime API i klucz API
- działający mikrofon i urządzenie wyjściowe
- PortAudio (na wielu systemach jest dostarczane przez system lub instalowane razem z backendem
  audio; na Debian/Ubuntu w razie potrzeby: `sudo apt install libportaudio2`)

Python 3.13 jest używany, ponieważ jest wspierany przez aktualne zależności i spełnia wymaganie
nowoczesnego Pythona bez wchodzenia w mniej dojrzałą kompatybilność 3.14.

## Installation

```bash
uv sync
```

`uv` sam pobierze właściwy interpreter 3.13, jeśli konfiguracja uv na to pozwala.

## Configuration

```bash
cp .env.example .env
```

Wpisz klucz w `.env` jako `OPENAI_API_KEY=...`. Plik `.env` jest ignorowany przez Git.

Opcjonalne ustawienia:

- `OPENAI_REALTIME_MODEL` — domyślnie `gpt-realtime-2.1`
- `OPENAI_REALTIME_VOICE` — domyślnie `marin` (OpenAI rekomenduje `marin` lub `cedar`
  dla najlepszej jakości)
- `AUDIO_INPUT_DEVICE` / `AUDIO_OUTPUT_DEVICE` — indeks lub nazwa urządzenia PortAudio
- `VOICE_DEBUG=1` — logi turnów, przerwań i transkrypcji

## Running

```bash
uv run python -m app
```

Mów normalnie; nie trzeba naciskać Enter ani push-to-talk. `Ctrl+C` kończy sesję i zamyka
urządzenia.

## Quality checks

```bash
uv run ruff check .
uv run mypy app
uv run pytest
```

## How interruption works

Mikrofon działa bez przerwy, także podczas odtwarzania odpowiedzi. Realtime API używa
`semantic_vad` z `interrupt_response=true`. Gdy serwer wykryje początek mowy użytkownika,
przerywa odpowiedź i SDK emituje `audio_interrupted`.

Odtwarzacz natychmiast i atomowo czyści ograniczony lokalny bufor przy tym evencie. Osobny
`RealtimePlaybackTracker` otrzymuje z callbacku PortAudio wyłącznie bajty faktycznie przekazane do
urządzenia. SDK odczytuje ten postęp podczas interruption i obcina (`conversation truncation`)
historię odpowiedzi do fragmentu, który został odtworzony; bajty oczekujące w lokalnym buforze nie
są raportowane jako usłyszane. Granicą zatrzymania jest jeden mały blok audio (20 ms).

## Testing language switching

W jednej sesji powiedz kolejno:

```text
"Hej, powiedz mi krótko czym jest Python."

"Actually, let's continue in English."

"What were we talking about?"

"Dobra, wróćmy do polskiego."
```

Agent powinien naturalnie przejść polski → angielski → polski bez ogłaszania zmiany.
W polskich odpowiedziach prompt osobno wymusza standardowy polski akcent, rytm, akcent wyrazowy i
intonację; nazwy produktów nie powinny zmieniać akcentu całego zdania.

## Testing barge-in

Powiedz:

```text
"Opowiedz mi historię o powstaniu Internetu."
```

Kiedy AI zacznie mówić, po około 2 sekundach przerwij:

```text
"Stop. Powiedz mi tylko w jednym zdaniu."
```

Oczekiwane zachowanie: stara wypowiedź natychmiast przestaje być odtwarzana, również z lokalnego
bufora, a agent odpowiada na najnowszą wypowiedź.

## Headphones

Do lokalnych testów full-duplex zdecydowanie zalecane są słuchawki. Bez acoustic echo
cancellation dźwięk z głośników może wracać do mikrofonu i powodować fałszywe przerwania lub
sprzężenie. Projekt świadomie nie implementuje własnego DSP/AEC; używa wejściowej redukcji szumu
Realtime w trybie `near_field`.

## Implementation notes

- wejście i wyjście to mono PCM16, 24 kHz, zgodnie z Realtime PCM audio;
- wyjście używa małego 60-ms jitter buffer, aby krótkie wahania dostarczania WebSocket nie
  powodowały trzasków i przerw; `audio_end` natychmiast zwalnia krótsze odpowiedzi;
- callback mikrofonu tylko kopiuje blok i przekazuje go thread-safe do ograniczonej kolejki asyncio;
- sieć nigdy nie działa w callbacku PortAudio;
- odbiór eventów, wysyłka mikrofonu i callback odtwarzania działają niezależnie;
- bufor mikrofonu jest ograniczony do 500 ms, a playback do 60 s (~2,9 MiB), więc pamięć nie rośnie
  bez końca, ale szybciej generowana odpowiedź nie jest ucinana;
- przekroczenie limitu playback kończy sesję czytelnym błędem — aplikacja nigdy nie odrzuca po
  cichu fragmentów odpowiedzi.

Pierwsze testy warto wykonywać ze słuchawkami i `VOICE_DEBUG=1`.
