# browser-agent

Stock browser harness + a **full second copy of Kev** + **human trajectory capture** + **FT scripts**, separate from [`../slitherio/`](../slitherio/).

| path | role |
|---|---|
| `jev-ultrafast/` | Upstream jev-ultrafast (`main`) + `--model jev\|kev` (flights / generic goals) |
| `kev/` | Full Kev train/serve tree for **this** track |
| `kev/runs/browser-agent-ft/` | Placeholder for the served FT checkpoint |
| `kev-finetune/` | Convert capture dumps + continue-train Kev (`train.py`) |
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

## Capture gold → convert → train

See [`browser-capture/README.md`](browser-capture/README.md) and [`kev-finetune/README.md`](kev-finetune/README.md).

```bash
cd browser-agent/browser-capture
python3 collector/server.py
# Load unpacked: browser-agent/browser-capture/extension
curl -s http://127.0.0.1:8787/v1/dataset > ../kev-finetune/potential_data/dataset.json
```

```bash
cd browser-agent/kev
uv run python ../kev-finetune/convert_capture.py
uv run python ../kev-finetune/train.py --check
uv run python ../kev-finetune/train.py --out ../kev/runs/browser-agent-ft-v1
```

Episodes also live in `browser-capture/data/episodes/` (gitignored per-run folders).

## Compare: hosted Jev vs local Kev

```bash
# A) Hosted Jev
cd browser-agent/jev-ultrafast
uv run --env-file .env python examples/flights.py --model jev
```

```bash
# B) Local FT Kev — after a run dir exists under kev/runs/
cd browser-agent/kev
uv run --extra serve python -m kev.serve --run runs/browser-agent-ft-v1 --port 8010
```

```bash
cd browser-agent/jev-ultrafast
uv run --env-file .env python examples/flights.py --model kev
# optional: --kev-url http://127.0.0.1:8010/v1/systemone
```

Same `--model` / `--kev-url` flags on `examples/run.py` and `uv run jev`.

## Teammate: dropping / serving the model

Train into a **new** folder (this script refuses overwrite):

```text
browser-agent/kev/runs/browser-agent-ft-v1/
```

Expected files: `adapter_model.safetensors`, `adapter_config.json`, `head.pt`, tokenizer files. See `kev/runs/browser-agent-ft/README.md`.

`--init` is `jaredpalmer/kev-0.5b` from the Hub — do not commit a machine-local `weights/original` symlink.
