# browser-agent

Stock browser harness + a **full second copy of Kev** + **human trajectory capture**, separate from [`../slitherio/`](../slitherio/).

| path | role |
|---|---|
| `jev-ultrafast/` | Upstream jev-ultrafast (`main`) + `--model jev\|kev` (flights / generic goals) |
| `kev/` | Full Kev train/serve tree for **this** track |
| `kev/runs/browser-agent-ft/` | **Drop the FT checkpoint here** (empty until trained) |
| `browser-capture/` | Chrome extension + local collector for real-user gold trajectories |

Default local Kev port for this track: **8010** (slitherio uses **8009**).  
Capture collector port: **8787**.

## Setup

```bash
cd browser-agent/jev-ultrafast
uv sync
cp .env.example .env   # OPENROUTER_API_KEY + TEXT_MODEL_API_KEY

cd ../kev
uv sync
uv sync --extra serve
```

## Capture real-user data (gold)

See [`browser-capture/README.md`](browser-capture/README.md).

```bash
cd browser-agent/browser-capture
python3 collector/server.py
# Load unpacked: browser-agent/browser-capture/extension
curl -s http://127.0.0.1:8787/v1/dataset
```

Episodes stay in `browser-capture/data/episodes/` (gitignored). That export is what you turn into a Kev training suite for `kev/runs/browser-agent-ft/`.

## Compare: hosted Jev vs local Kev

```bash
# A) Hosted Jev
cd browser-agent/jev-ultrafast
uv run --env-file .env python examples/flights.py --model jev
```

```bash
# B) Local FT Kev — after weights are in kev/runs/browser-agent-ft/
cd browser-agent/kev
uv run --extra serve python -m kev.serve --run runs/browser-agent-ft --port 8010
```

```bash
cd browser-agent/jev-ultrafast
uv run --env-file .env python examples/flights.py --model kev
# optional: --kev-url http://127.0.0.1:8010/v1/systemone
```

Same `--model` / `--kev-url` flags on `examples/run.py` and `uv run jev`.

## Teammate: dropping the model

Put the checkpoint files in:

```text
browser-agent/kev/runs/browser-agent-ft/
```

Expected files (same as a normal Kev `--out` run): `adapter_model.safetensors`, `adapter_config.json`, `head.pt`, tokenizer files, etc. See `kev/runs/browser-agent-ft/README.md`.

Then update defaults if the port/path changes:

- `jev-ultrafast/jev_ultrafast/model.py` → `DEFAULT_KEV_URL`
- comments in `jev-ultrafast/.env.example` and this README
