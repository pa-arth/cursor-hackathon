# browser-agent-ft

**Drop / train a fine-tuned Kev checkpoint here** (or a sibling `browser-agent-ft-vN/` if this folder is already used). Same layout as `slitherio/kev/runs/slither-ft-v2/`.

Train from [`../../kev-finetune/`](../../kev-finetune/):

```bash
cd browser-agent/kev
uv run python ../kev-finetune/train.py --out ../kev/runs/browser-agent-ft-v1
```

Expected files:

- `adapter_model.safetensors`
- `adapter_config.json`
- `head.pt`
- tokenizer files (`tokenizer.json`, `vocab.json`, …)
- `training_config.json` / `training_metrics.json` (optional)

Then serve:

```bash
cd browser-agent/kev
uv sync --extra serve
uv run --extra serve python -m kev.serve --run runs/browser-agent-ft --port 8010
```

Harness (from `browser-agent/jev-ultrafast`):

```bash
uv run --env-file .env python examples/flights.py --model kev
```
