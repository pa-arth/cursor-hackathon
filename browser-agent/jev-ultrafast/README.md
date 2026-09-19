# jev-ultrafast (browser-agent harness)

Upstream [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) with `--model jev|kev`.

Parent folder docs: [`../README.md`](../README.md).

```bash
# from browser-agent/jev-ultrafast
cp .env.example .env   # TEXT_MODEL_API_KEY for typing; OPENROUTER only for --model jev
uv run python examples/flights.py --model jev
uv run python examples/flights.py --model kev   # kev.serve on :8010; still needs TEXT_MODEL for fills
```

FT checkpoint path (sibling tree): `../kev/runs/browser-agent-ft/`.
