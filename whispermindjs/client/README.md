# WhisperMind React Client

React client for the WhisperMind JS UI. The server in `../server` serves this build in production and provides the REST + Socket.IO backend.

## Scripts

```bash
npm start
npm run build
npm run test:e2e
```

- `npm start`: Create React App dev server. API calls proxy to `http://localhost:5000`.
- `npm run build`: production bundle served by `whispermindjs/server`.
- `npm run test:e2e`: Playwright browser smoke test. It expects a running JS server and defaults to `http://127.0.0.1:5010`.

Override the smoke-test URL when needed:

```bash
WHISPERMIND_URL=http://127.0.0.1:5000 npm run test:e2e
```

## Smoke Test Coverage

The browser smoke test checks that:

- the app reaches `Ready` without showing `Disconnected from backend`;
- `Generate Suggestions` returns the no-recent-conversation message cleanly;
- switching to `OpenAI Realtime Translation` and immediately starting recording uses the selected mode, even before the settings save round trip finishes;
- missing `OPENAI_API_KEY` resets the UI back to `Start Recording`;
- the settings panel can be hidden and shown again;
- browser console errors and page errors fail the test.

Screenshots are written to `/tmp/whispermind-ui-ready.png` and `/tmp/whispermind-ui-realtime-error.png`.
