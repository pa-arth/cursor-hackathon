# Browser Capture

Ambient, element-grounded trajectory capture for local browser-agent fine-tuning.

You browse normally. The Chrome extension maps clicks / fills / selects / scrolls onto the same indexed action table as [jev-ultrafast](../jev-ultrafast) (`snapshot.js`), tags them with an **intent**, and appends steps to a local collector.

## Layout

```text
browser-capture/
  extension/          Chrome MV3 side panel + content script
  collector/server.py Loopback HTTP → data/episodes/<id>/
  data/episodes/      meta.json + steps.jsonl per episode
```

## 1. Start the collector

```bash
cd browser-capture
python3 collector/server.py
```

Health check: [http://127.0.0.1:8787/health](http://127.0.0.1:8787/health)

Episodes land in `browser-capture/data/episodes/<id>/`:

- `meta.json` — intent, status, success, timestamps
- `steps.jsonl` — one observation→action step per line

## 2. Load the extension

1. Chrome → `chrome://extensions`
2. Enable **Developer mode**
3. **Load unpacked** → select `browser-capture/extension`
4. Pin **Browser Capture** and open the side panel (toolbar icon)

## 3. Record a task

1. Type an **intent** (goal) in the side panel
2. Optional: host allowlist, e.g. `google.com, github.com`
3. Click **Record**, do the task in the page
4. **Done** (optionally uncheck success if it failed)

Pause anytime. Steps only flow while recording and unpaused.

## Step schema

Each `steps.jsonl` line looks like:

```json
{
  "step": 1,
  "ts": "2026-09-19T18:00:00+00:00",
  "url": "https://…",
  "mapped": true,
  "gesture": "click",
  "observation": {
    "url": "…",
    "title": "…",
    "text": "…",
    "actions": [{ "id": "e3", "kind": "click", "label": "Search", "node": 12, "role": "button" }]
  },
  "action": { "id": "e3", "kind": "click", "label": "Search", "node": 12, "role": "button" }
}
```

Fills include `action.text`. Unmapped gestures set `mapped: false` (skip for training by default).

## API (collector)

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness + episode count |
| `GET` | `/v1/episodes` | List episode metas |
| `POST` | `/v1/episodes` | Start `{ id, intent, start_url?, allowlist? }` |
| `POST` | `/v1/episodes/:id/steps` | Append one step |
| `POST` | `/v1/episodes/:id/complete` | Seal `{ success, notes? }` |

## Next (not in this PR)

- Supabase local as an index over the same JSONL
- Nightly LaunchAgent → pack SFT rows → fine-tune a small local model
- Filter `mapped=true` + `success=true` before training

## Privacy

- Password / file / hidden inputs are excluded from the snapshot
- Prefer an allowlist for daily use
- Data stays on `127.0.0.1` unless you point the collector elsewhere
