# WhisperMind JS UI

React + Express/Socket.IO UI for the current WhisperMind backend behavior. The Tkinter app remains the reference UI; this JS UI is adapted to the same backend modes, model names, language sets, config validation, suggestion behavior, and local `.env` credentials.

## Layout

```text
whispermindjs/
  client/   React UI and Playwright smoke tests
  server/   Express, Socket.IO, config, transcription, realtime adapters
```

The server loads environment variables from the repository root `.env` first, then from `whispermindjs/server/.env` if present. This keeps the JS UI aligned with the Tk UI keys while still allowing JS-specific overrides.

## Run

Install dependencies once:

```bash
cd whispermindjs/server
npm ci

cd ../client
npm ci
```

Development mode uses the CRA dev server and API proxy:

```bash
cd whispermindjs/server
npm start
```

```bash
cd whispermindjs/client
npm start
```

The client dev server proxies API calls to `http://localhost:5000`.

Production/local single-server mode:

```bash
cd whispermindjs/client
npm run build

cd ../server
PORT=5010 npm start
```

Then open `http://127.0.0.1:5010`. The Express server serves `client/build` and the API/socket backend on the same origin.

## Persistent macOS LaunchAgent

The local audited launch uses a per-user LaunchAgent:

- label: `com.whispermind.jsui`
- URL: `http://127.0.0.1:5010`
- working directory: `whispermindjs/server`
- logs: `/tmp/whispermind-js-5010.log` and `/tmp/whispermind-js-5010.err`

Useful commands:

```bash
launchctl print gui/$(id -u)/com.whispermind.jsui
launchctl kickstart -k gui/$(id -u)/com.whispermind.jsui
tail -f /tmp/whispermind-js-5010.log
tail -f /tmp/whispermind-js-5010.err
```

If the LaunchAgent is not installed on a machine, use the production/local single-server commands above.

## Backend Modes

- `Legacy Groq Whisper + Groq Translate`
- `OpenAI GPT-4o Transcribe + Translate`
- `OpenAI Realtime Translation`

Realtime mode streams browser PCM audio to the JS server, then to OpenAI realtime translation. File transcription uses the chunked backend when realtime is selected.

## API Keys

The JS server can start with missing providers, but unavailable modes fail explicitly:

- `GROQ_API_KEY`: legacy Groq transcription and translation.
- `ANTHROPIC_API_KEY`: suggestions and transliteration.
- `OPENAI_API_KEY`: OpenAI chunked transcription/translation and realtime translation.

Check provider availability:

```bash
curl -fsS http://127.0.0.1:5010/api/health | jq .
```

Expected shape:

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

`openai: false` means OpenAI modes will show a clear `OPENAI_API_KEY` error. Legacy Groq mode and Anthropic suggestions can still work if their keys are present.

## Verification

Server syntax check:

```bash
cd whispermindjs/server
npm run check
```

Production React build:

```bash
cd whispermindjs/client
npm run build
```

Browser smoke test against the running server:

```bash
cd whispermindjs/client
WHISPERMIND_URL=http://127.0.0.1:5010 npm run test:e2e
```

The Playwright smoke test verifies that the UI stays connected, never shows `Disconnected from backend` during the startup wait, renders `Ready`, generates the empty-history suggestion message, handles the missing OpenAI realtime key without getting stuck in recording state, toggles settings, and reports browser console/page errors as test failures.

The test writes screenshots to:

- `/tmp/whispermind-ui-ready.png`
- `/tmp/whispermind-ui-realtime-error.png`

## Operational Checks

After launch, run:

```bash
curl -fsS http://127.0.0.1:5010/api/health
curl -fsS http://127.0.0.1:5010/api/config | jq '{recordingPeriod, translationBackend, translationLanguage, showOriginal, showSuggestions, profiles}'
```

The default stable state after verification should be legacy mode:

```json
{
  "recordingPeriod": 5,
  "translationBackend": "Legacy Groq Whisper + Groq Translate",
  "translationLanguage": "English",
  "showOriginal": true,
  "showSuggestions": true,
  "profiles": {}
}
```
