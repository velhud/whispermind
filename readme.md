# WhisperMind

WhisperMind is a local app for live microphone transcription, translation, and conversation suggestions. The Tkinter UI is the reference desktop UI; the JS UI in `whispermindjs/` mirrors the same backend modes through a local React + Express/Socket.IO app.

## Launch

```bash
python3 -m pip install -r requirements.txt
python3 whispermind.py
```

The JS UI lives in `whispermindjs/` and mirrors the current Tk backend modes. See `whispermindjs/README.md` for install, launch, persistent LaunchAgent, and browser smoke-test steps.

If PyAudio fails on macOS, install PortAudio first and rebuild PyAudio:

```bash
brew install portaudio
CFLAGS="-I/opt/homebrew/include" LDFLAGS="-L/opt/homebrew/lib" \
  python3 -m pip install --force-reinstall --no-binary :all: --no-cache-dir pyaudio
```

## API Keys

Create `.env` from `.env.example`:

```plaintext
GROQ_API_KEY=your_groq_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key
OPENAI_API_KEY=your_openai_api_key
```

The app launches without every key, but each backend needs its own key:

- `GROQ_API_KEY`: required for `Legacy Groq Whisper + Groq Translate`.
- `ANTHROPIC_API_KEY`: required for conversation suggestions and transliteration.
- `OPENAI_API_KEY`: required for both OpenAI chunked and OpenAI realtime modes.

The JS server exposes key availability at `/api/health`, for example:

```json
{
  "ok": true,
  "providers": {
    "groq": true,
    "openai": false,
    "anthropic": true
  }
}
```

## Translation Backends

Choose the backend in the settings panel:

- `Legacy Groq Whisper + Groq Translate`: existing chunked flow using Groq `whisper-large-v3` for transcription and `llama-3.3-70b-versatile` for text translation.
- `OpenAI GPT-4o Transcribe + Translate`: chunked microphone/file flow using OpenAI `gpt-4o-transcribe` plus `gpt-4.1-mini` text translation.
- `OpenAI Realtime Translation`: streaming microphone translation with OpenAI `gpt-realtime-translate` over the dedicated `/v1/realtime/translations` WebSocket endpoint.

OpenAI realtime translation requires `OPENAI_API_KEY` and streams 24 kHz mono PCM audio. The app displays source transcript deltas in the original column and translated transcript deltas in the translated column. File transcription uses the chunked OpenAI backend when realtime mode is selected, because realtime translation is microphone-only.

## Controls

- Press Enter or click `Start Recording` to start/stop recording.
- Press Space or click `Generate Suggestions` to generate suggestions from the last 5 minutes of source transcripts.
- Keyboard shortcuts are ignored while editing settings fields.
- Use `Translate To` for the target language.
- Realtime translation target languages are limited to the output languages supported by `gpt-realtime-translate`.
- Recording chunk length is clamped to 1-30 seconds.
- `Clear` clears both visible text and the suggestion history.
- Use `Save Settings` to persist backend, language, display, profile, and personal-info settings.

## Notes

- The old Groq translation model was decommissioned; this version uses `llama-3.3-70b-versatile`.
- The old Anthropic Sonnet model was unavailable for the configured key; this version uses `claude-sonnet-4-6`.
- If `OPENAI_API_KEY` is missing, OpenAI modes fail clearly in the UI instead of silently recording against the wrong backend.
- OpenAI official docs used for the integration:
  - https://developers.openai.com/api/docs/guides/speech-to-text
  - https://developers.openai.com/api/docs/guides/realtime-transcription
  - https://developers.openai.com/api/docs/guides/realtime-translation
