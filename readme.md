# WhisperMind

WhisperMind is a local Tkinter app for live microphone transcription, translation, and conversation suggestions.

## Launch

```bash
python3 -m pip install -r requirements.txt
python3 whispermind.py
```

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

The app launches without every key, but each backend needs its own key.

## Translation Backends

Choose the backend in the settings panel:

- `Legacy Groq Whisper + Groq Translate`: existing chunked flow using Groq `whisper-large-v3` for transcription and `llama-3.3-70b-versatile` for text translation.
- `OpenAI GPT-4o Transcribe + Translate`: chunked microphone/file flow using OpenAI `gpt-4o-transcribe` plus `gpt-4.1-mini` text translation.
- `OpenAI Realtime Translation`: streaming microphone translation with OpenAI `gpt-realtime-translate` over the dedicated `/v1/realtime/translations` WebSocket endpoint.

OpenAI realtime translation requires `OPENAI_API_KEY` and streams 24 kHz mono PCM audio. The app displays source transcript deltas in the original column and translated transcript deltas in the translated column.

## Controls

- Press Enter or click `Start Recording` to start/stop recording.
- Press Space to generate conversation suggestions from the last 5 minutes of source transcripts.
- Use `Translate To` for the target language.
- Use `Save Settings` to persist backend, language, display, profile, and personal-info settings.

## Notes

- The old Groq translation model was decommissioned; this version uses `llama-3.3-70b-versatile`.
- The old Anthropic Sonnet model was unavailable for the configured key; this version uses `claude-sonnet-4-6`.
- OpenAI official docs used for the integration:
  - https://developers.openai.com/api/docs/guides/speech-to-text
  - https://developers.openai.com/api/docs/guides/realtime-transcription
  - https://developers.openai.com/api/docs/guides/realtime-translation
