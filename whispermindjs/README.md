# WhisperMind JS UI

React + Express/Socket.IO UI for the current WhisperMind backend behavior.

## Run

```bash
cd server
cp .env.example .env
npm ci
npm start
```

```bash
cd client
npm ci
npm start
```

The client dev server proxies API calls to `http://localhost:5000`. For production, run `npm run build` in `client`; the Express server serves `client/build`.

## Backend Modes

- `Legacy Groq Whisper + Groq Translate`
- `OpenAI GPT-4o Transcribe + Translate`
- `OpenAI Realtime Translation`

Realtime mode streams browser PCM audio to the JS server, then to OpenAI realtime translation. File transcription uses the chunked backend when realtime is selected.
