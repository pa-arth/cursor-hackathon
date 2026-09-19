# Kev browser fine-tune

Separate from `jev-ultrafast`. Continues a Kev checkpoint on labelled click/type decisions.

## Data

Paired files, same name:

- `data/inputs/<id>.json` — page state + TypeSafe questions (no labels)
- `data/outputs/<id>.json` — `{ "<question_id>": "<option key>" }`

The output value must be a key from that question's `criteria`, not a sentence.

## Capture dumps

If a JSON export lands in `potential_data/` (`browser-capture.element_grounded.v1`):

```bash
../kev/.venv/bin/python convert_capture.py
../kev/.venv/bin/python train.py --check
```

That writes `data/inputs/capture-*.json` and matching outputs, using jev-ultrafast element indexes. Typed strings are not trained.

## Weights

| What | Where |
|---|---|
| Original `kev-0.5b` adapter | Hugging Face cache (`~/.cache/huggingface/hub/models--jaredpalmer--kev-0.5b`). Also `weights/original/` |
| Frozen Qwen 0.5B backbone | `~/.cache/huggingface/hub/models--Qwen--Qwen2.5-0.5B` (shared, never overwritten) |
| Fine-tunes | `weights/finetuned/<name>/` |

`--init` is read-only. `--out` must be a new folder.

## Run

Smoke (1 example, 1 epoch):

```bash
cd kev-finetune
../kev/.venv/bin/python train.py --limit 1 --epochs 1 --accum 1 --out weights/finetuned/smoke
```

Full set:

```bash
../kev/.venv/bin/python train.py --out weights/finetuned/browser-sft
```

Serve original vs fine-tune:

```bash
cd ../kev
.venv/bin/python -m kev.serve --run ../kev-finetune/weights/original --port 8009
.venv/bin/python -m kev.serve --run ../kev-finetune/weights/finetuned/smoke --port 8009
```
