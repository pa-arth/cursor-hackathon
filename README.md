# cursor-hackathon

Hackathon POC: **fine-tune Kev on human slither.io play**, then drive the game with that local decision model.

This repo vendors two projects as **normal folders** (not git submodules):

| folder | what it is |
|---|---|
| `jev-ultrafast/` | Browser harness + slither sensors, AIM actions, human recording |
| `kev/` | Decision-model train/serve code + our FT checkpoint |

## What’s included

- Human trajectory logger (`jev-ultrafast/examples/slither_demo.py --human`)
- Recorded gold labels → `jev-ultrafast/artifacts/slither-data/`
- Kev suite export → `jev-ultrafast/artifacts/slither-suite/`
- Fine-tuned adapter → `kev/runs/slither-ft-v2/`

No API keys are committed (`.env` is gitignored).

## Quick start

### 1. Record more human play (optional)

```bash
cd jev-ultrafast
uv sync
uv run python examples/slither_demo.py --human
```

### 2. Export suite + train (already done once)

```bash
cd jev-ultrafast
uv run python examples/export_slither_suite.py \
  --in artifacts/slither-data --out artifacts/slither-suite

cd ../kev
uv sync
uv run python -m kev.train \
  --suite ../jev-ultrafast/artifacts/slither-suite \
  --base Qwen/Qwen2.5-0.5B --epochs 2 --lr 5e-5 --accum 4 --device mps \
  --out runs/slither-ft-v2
```

### 3. Serve the fine-tune + play

```bash
cd kev
uv sync --extra serve
uv run --extra serve python -m kev.serve --run runs/slither-ft-v2 --port 8009
```

```bash
cd jev-ultrafast
TYPESAFE_BASE_URL=http://127.0.0.1:8009/v1/systemone TYPESAFE_API_KEY=local \
  uv run python examples/slither_demo.py --unlimited --no-guardrails
```

## Quantifying “better”

1. **Offline:** `kev.benchmark` on `artifacts/slither-suite` development split — FT vs `jaredpalmer/kev-0.5b` accuracy on held-out human AIM labels.
2. **Online:** ~10 games each (same flags) — median peak length / steps survived.
