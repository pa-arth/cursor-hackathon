# jev-ultrafast (browser-agent harness)

Upstream [jev-ultrafast](https://github.com/browser-use/jev-ultrafast) with `--model jev|kev`.

Parent folder docs: [`../README.md`](../README.md).

```bash
# from browser-agent/jev-ultrafast
uv run --env-file .env python examples/flights.py --model jev
uv run --env-file .env python examples/flights.py --model kev   # needs kev.serve on :8010
```

FT checkpoint path (sibling tree): `../kev/runs/browser-agent-ft/`.
