# Kev browser fine-tune

Lives at `browser-agent/kev-finetune/`. Continues a Kev checkpoint on labelled click/type decisions using the sibling trees:

| sibling | used for |
|---|---|
| `../kev/` | train/serve code + `uv` env |
| `../jev-ultrafast/` | action-space indexes in `convert_capture.py` |
| `../browser-capture/` | gold dumps (`/v1/dataset` → `potential_data/` or `--src`) |

## Data

Paired files, same name:

- `data/inputs/<id>.json` — page state + TypeSafe questions (no labels)
- `data/outputs/<id>.json` — `{ "<question_id>": "<option key>" }`

The output value must be a key from that question's `criteria`, not a sentence.

## Capture dumps

If a JSON export lands in `potential_data/` (`browser-capture.element_grounded.v1`):

```bash
cd browser-agent/kev
uv sync
uv run python ../kev-finetune/convert_capture.py
uv run python ../kev-finetune/train.py --check
```

That writes `data/inputs/capture-*.json` and matching outputs, using jev-ultrafast element indexes. Typed strings are not trained.

From the collector:

```bash
curl -s http://127.0.0.1:8787/v1/dataset > ../kev-finetune/potential_data/dataset.json
```

## Weights

| What | Where |
|---|---|
| Original `kev-0.5b` | Hub id `jaredpalmer/kev-0.5b` (`--init`, Hugging Face cache). Do **not** commit a local `weights/original` symlink. |
| Frozen Qwen 0.5B backbone | `~/.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B` (shared, never overwritten) |
| Local training runs | `weights/finetuned/<name>/` (gitignored) |
| Demo checkpoint | `../kev/runs/browser-agent-ft/` (or `browser-agent-ft-vN` if that folder already exists) |

`--init` is read-only. `--out` must be a new folder (`kev.train` / this script refuse overwrite).

## Run

Smoke (1 example, 1 epoch):

```bash
cd browser-agent/kev
uv run python ../kev-finetune/train.py --limit 1 --epochs 1 --accum 1 \
  --out ../kev-finetune/weights/finetuned/smoke
```

Full set → new demo run dir (pick a name that does not already exist):

```bash
cd browser-agent/kev
uv run python ../kev-finetune/train.py --out ../kev/runs/browser-agent-ft-v1
```

Serve the fine-tune (this track uses **8010**, not slither’s 8009):

```bash
cd browser-agent/kev
uv sync --extra serve
uv run --extra serve python -m kev.serve --run runs/browser-agent-ft-v1 --port 8010
```

Then from `browser-agent/jev-ultrafast`:

```bash
uv run --env-file .env python examples/flights.py --model kev
```
