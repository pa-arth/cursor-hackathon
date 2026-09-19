# Browser Capture

Ambient, element-grounded trajectory capture for local browser-agent fine-tuning.

You browse normally. The Chrome extension maps clicks / fills / selects / scrolls onto the same indexed action table as [jev-ultrafast](../jev-ultrafast) (`snapshot.js`) and appends steps to a **local** collector. Intent defaults to **auto-suggest on Done** via your LLM API key (encrypted at rest).

## Privacy

- **Episode trajectories never leave this machine** (`data/episodes/`).
- Intent suggestion sends only a short step summary (labels / fill text / URLs) to the model provider you configure.
- The API key is stored in the **macOS Keychain** when available, otherwise AES-GCM encrypted under a local `0600` master key in `data/secrets/` (gitignored).

## Layout

```text
browser-capture/
  extension/                 Chrome MV3 side panel + content script
  collector/server.py        Loopback HTTP
  collector/credential_store.py
  data/episodes/             meta.json + steps.jsonl per episode
  data/secrets/              encrypted key / settings (local only)
```

## 1. Start the collector

```bash
cd browser-capture
python3 collector/server.py
```

Off macOS, install crypto for file-backed keys:

```bash
pip install cryptography
```

Health: [http://127.0.0.1:8787/health](http://127.0.0.1:8787/health)

## 2. Load the extension

1. Chrome → `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → `browser-capture/extension`
4. Open the side panel → **LLM settings** → paste API key → **Save key**

Default endpoint is OpenRouter (`https://openrouter.ai/api/v1` + `openai/gpt-4o-mini`). Any OpenAI-compatible base URL works.

## 3. Record a task

1. Leave **Intent** blank (or type your own)
2. Optional host allowlist (`google.com`)
3. **Record** → do the task → **Done · suggest intent**

If intent was blank and a key is saved, the collector labels the episode (`intent_source: "llm"`). Typed intents stay `human`.

## Step schema

Each `steps.jsonl` line:

```json
{
  "step": 1,
  "mapped": true,
  "gesture": "click",
  "observation": { "url": "…", "actions": [{ "id": "e3", "kind": "click", "label": "Search" }] },
  "action": { "id": "e3", "kind": "click", "label": "Search" }
}
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness + key configured? |
| `GET` | `/v1/settings` | Key status (never returns the raw key) |
| `POST` | `/v1/settings/api-key` | Save encrypted key + optional model/URL |
| `DELETE` | `/v1/settings/api-key` | Clear key |
| `POST` | `/v1/episodes` | Start (`intent` optional) |
| `POST` | `/v1/episodes/:id/steps` | Append step |
| `POST` | `/v1/episodes/:id/complete` | Seal; auto-suggest intent if empty |
| `POST` | `/v1/episodes/:id/suggest-intent` | Suggest without sealing |
