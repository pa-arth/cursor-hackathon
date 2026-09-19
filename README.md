# cursor-hackathon

Hackathon POC: drive a browser agent on **slither.io** with either **hosted Jev** (API key) or a **local fine-tuned Kev**, collect **human gold** play, and keep fine-tuning.

`jev-ultrafast/` and `kev/` are normal folders in this repo (not git submodules).

| folder | role |
|---|---|
| `jev-ultrafast/` | Browser harness, slither sensors / AIM actions, human recording, demo CLI |
| `kev/` | Train + serve decision models; ships our FT checkpoint `runs/slither-ft-v2/` |

The harness can run other browser goals too; the sensors, recording, and FT loop here are built for slither.

---

## Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/)
- Chrome available for [browser-harness](https://github.com/browser-use/browser-harness) (first run may prompt you to connect/debug)
- For `--model jev`: an [OpenRouter](https://openrouter.ai/) key with Decisions access
- For `--model kev`: enough RAM/GPU (Apple MPS is fine for the 0.5B FT)

```bash
git clone https://github.com/pa-arth/cursor-hackathon.git
cd cursor-hackathon
```

```bash
cd jev-ultrafast && uv sync && cp .env.example .env   # then edit .env
cd ../kev && uv sync && uv sync --extra serve
```

Put `OPENROUTER_API_KEY=...` (and usually the same value as `TEXT_MODEL_API_KEY` for typing the nickname) in `jev-ultrafast/.env`. Never commit `.env`.

---

## Play slither: Jev vs Kev

### A) Hosted Jev (OpenRouter)

```bash
cd jev-ultrafast
uv run --env-file .env python examples/slither_demo.py \
  --model jev --unlimited --no-guardrails
```

### B) Local fine-tuned Kev

Terminal 1 — serve the checkpoint (first load downloads the Qwen base):

```bash
cd kev
uv run --extra serve python -m kev.serve --run runs/slither-ft-v2 --port 8009
```

Terminal 2 — point the demo at it:

```bash
cd jev-ultrafast
uv run python examples/slither_demo.py \
  --model kev --unlimited --no-guardrails
```

`--model kev` sets `TYPESAFE_BASE_URL=http://127.0.0.1:8009/v1/systemone` for you. Override with `--kev-url` if needed.

### Flags worth knowing

| flag | meaning |
|---|---|
| `--model jev\|kev` | Hosted Jev (API) vs local Kev server |
| `--no-guardrails` | Keep all AIM options visible (needed for fair compare / FT) |
| `--guardrails` | Demo seatbelts: hide UNSAFE aims (default on if you omit `--no-guardrails`) |
| `--unlimited` | Run until Ctrl+C |
| `--human` | You play; record gold labels (no model calls) |
| `--record` | Log AIM choices from jev/kev/teacher into JSONL |
| `--teacher` | Silver labels from sensor `recommended_dir` (not human) |

---

## Fine-tuning loop (human gold → better Kev)

**Idea:** gym (sensors + AIM action space) stays in code. Policy improves by fine-tuning Kev on labeled AIM choices. Human mouse play = **gold**. Sensor teacher / agent self-play = weaker silver.

### 1. Record your play

```bash
cd jev-ultrafast
uv run python examples/slither_demo.py --human
```

Focus the Chrome tab → nick → Play → steer with the mouse (hold click/space to boost). Ctrl+C when done.

Each session appends a new file under `artifacts/slither-data/human-*.jsonl`. Run this as many times as you want; more gold → clearer FT gains.

### 2. Build / refresh the Kev training suite

Export **merges all** `*.jsonl` under the data dir (old + new):

```bash
cd jev-ultrafast
uv run python examples/export_slither_suite.py \
  --in artifacts/slither-data \
  --out artifacts/slither-suite
```

States are compacted to fit Kev’s 384-token training budget.

### 3. Train a new checkpoint

`kev.train` **refuses to overwrite** an existing `--out` directory — pick a new name each time:

```bash
cd kev
uv run python -m kev.train \
  --suite ../jev-ultrafast/artifacts/slither-suite \
  --base Qwen/Qwen2.5-0.5B \
  --epochs 2 --lr 5e-5 --accum 4 --device mps \
  --out runs/slither-ft-v3
```

Then serve `runs/slither-ft-v3` and use `--model kev` as above.

Shipped baseline from this hackathon: `kev/runs/slither-ft-v2/` (trained on the included human JSONL).

### Label quality reminder

| source | how | quality |
|---|---|---|
| `--human` | your mouse → AIM octant / boost | **gold** |
| `--record --teacher` | sensor `recommended_dir` | silver |
| `--record` with `--model jev\|kev` | whatever the model chose | weak |

Prefer gold for real progress. Guardrails are demo seatbelts, not the training signal — record/train with `--no-guardrails` so unsafe options stay in the choice set.

---

## Is the new model actually better?

1. **Offline:** held-out human AIM accuracy on the suite’s development split — FT vs base Kev:

```bash
cd kev
uv run python -m kev.benchmark --run jaredpalmer/kev-0.5b \
  --suite ../jev-ultrafast/artifacts/slither-suite --out runs/slither-base-eval --device mps
uv run python -m kev.benchmark --run runs/slither-ft-v2 \
  --suite ../jev-ultrafast/artifacts/slither-suite --out runs/slither-ft-eval --device mps
```

Chance with 8 aims ≈ 12.5%.

2. **Online:** ~10 games each of `--model jev` vs `--model kev` (same `--no-guardrails`). Compare median peak length / steps survived.

With only a few hundred human samples, expect a small noisy edge — more `--human` sessions make the gap clearer.

---

## What’s in the repo

- Human trajectory logger + mouse intent capture
- Sample gold data: `jev-ultrafast/artifacts/slither-data/`
- Frozen-ish suite: `jev-ultrafast/artifacts/slither-suite/`
- FT adapter: `kev/runs/slither-ft-v2/`
- Root `.gitignore` keeps `.env` / `.venv` out; no nested `.git` folders
