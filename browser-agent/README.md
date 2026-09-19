# browser-agent

Stock [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) (upstream `main`) with a thin `--model jev|kev` switch so you can compare **hosted Jev** vs a **local fine-tuned Kev** on the built-in flights / generic browser tasks.

This is **not** the slither stack — that lives in [`../slitherio/`](../slitherio/). No game sensors or human-recording code here.

## Setup

```bash
cd browser-agent
uv sync
cp .env.example .env   # add OPENROUTER_API_KEY (+ TEXT_MODEL_API_KEY for typing)
```

## Run flights (compare)

```bash
# Hosted Jev (OpenRouter Decisions)
uv run --env-file .env python examples/flights.py --model jev

# Local Kev — teammate serves System One first (default :8010)
# TODO(team): document the exact `kev.serve --run …` once the FT checkpoint is in this folder
uv run --env-file .env python examples/flights.py --model kev
# or:  --model kev --kev-url http://127.0.0.1:8010/v1/systemone
```

Same flags on:

```bash
uv run --env-file .env python examples/run.py --model jev --url URL --goal '…'
uv run --env-file .env jev --model jev    # inspector UI
```

## Teammate checklist (when the second FT model lands)

Update these so defaults match the real server:

1. Drop / document the checkpoint path (e.g. `runs/browser-agent-ft/`).
2. `DEFAULT_KEV_URL` in `jev_ultrafast/model.py` (and comments in `.env.example` / this README).
3. Serve command in this README (`kev.serve --run … --port 8010`).

Any System One URL works with `--kev-url` (even slither’s `:8009`); this track’s default stays `:8010` to avoid collisions.
