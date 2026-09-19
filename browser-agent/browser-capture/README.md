# Browser Capture

Ambient, element-grounded trajectory capture for local **browser-agent** fine-tuning.

Lives at `browser-agent/browser-capture/` (sibling of `jev-ultrafast/` and `kev/`).

You browse normally. The Chrome extension maps clicks / fills / selects / scrolls onto the same indexed action table as [jev-ultrafast](../jev-ultrafast) (`snapshot.js`) and appends steps to a **local** collector. Intent defaults to **auto-suggest on Done** via your LLM API key (encrypted at rest).

The episode files under `data/episodes/` are the trajectories **Kev was fine-tuned on** for this track (`kev/runs/browser-agent-ft/`). Capture more with the extension; it does **not** overwrite harness or Kev source.


## Fine-tuning data

Kev for `browser-agent` was fine-tuned on the trajectories in [`data/episodes/`](data/episodes/). Each episode directory has:

- `meta.json` — goal/intent, success, timestamps
- `steps.jsonl` — element-grounded observation → action steps

Use `GET http://127.0.0.1:8787/v1/dataset` (collector running) to pack them into training examples.

## Privacy

- **Episode trajectories are stored under** `data/episodes/` (checked-in FT set + any local captures).
- Intent suggestion sends only a short step summary (labels / fill text / URLs) to the model provider you configure.
- The API key is stored in the **macOS Keychain** when available, otherwise AES-GCM encrypted under a local `0600` master key in `data/secrets/` (gitignored).

## Layout

```text
browser-agent/
  jev-ultrafast/             # run / compare with --model jev|kev
  kev/                       # train + serve; drop FT weights in runs/browser-agent-ft/
  browser-capture/           # this package
    extension/               # Chrome MV3 side panel + content script
    collector/server.py      # Loopback HTTP (:8787)
    collector/credential_store.py
    data/episodes/           # meta.json + steps.jsonl — Kev FT training trajectories
    data/secrets/            # encrypted key / settings (local only)
```

## 1. Start the collector

```bash
cd browser-agent/browser-capture
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
3. **Load unpacked** → `browser-agent/browser-capture/extension`
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
| `GET` | `/v1/dataset` | **Training export**: episodes + per-step examples |
| `GET` | `/v1/examples?success_only=true` | Flat training examples only |
| `GET` | `/v1/episodes?include_steps=true` | All episodes with raw steps |
| `GET` | `/v1/episodes/:id` | One episode + steps |
| `GET` | `/v1/settings` | Key status (never returns the raw key) |
| `POST` | `/v1/settings/api-key` | Save encrypted key + optional model/URL |
| `DELETE` | `/v1/settings/api-key` | Clear key |
| `POST` | `/v1/episodes` | Start (`intent` optional) |
| `POST` | `/v1/episodes/:id/steps` | Append step |
| `POST` | `/v1/episodes/:id/complete` | Seal; auto-suggest intent if empty |
| `POST` | `/v1/episodes/:id/suggest-intent` | Suggest without sealing |

### Training export

```bash
curl -s http://127.0.0.1:8787/v1/dataset | python3 -m json.tool | less
curl -s 'http://127.0.0.1:8787/v1/examples?success_only=true'
```

Each `examples[]` row is one supervised step:

- `prompt.goal` + `prompt.action_space` (indexed elements) + `prompt.history`
- `completion.action_id` / `kind` / `text` (for fills)

Query flags on `/v1/dataset`: `mapped_only` (default true), `success_only` (default false), `complete_only` (default true).

Export → convert + train with sibling [`../kev-finetune/`](../kev-finetune/):

```bash
curl -s http://127.0.0.1:8787/v1/dataset > ../kev-finetune/potential_data/dataset.json
cd ../kev
uv run python ../kev-finetune/convert_capture.py
uv run python ../kev-finetune/train.py --out ../kev/runs/browser-agent-ft-v1
```

See parent [`../README.md`](../README.md).
