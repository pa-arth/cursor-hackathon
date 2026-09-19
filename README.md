# cursor-hackathon

**Main track: [`browser-agent/`](browser-agent/)** — a stock browser harness that can run on **hosted Jev** or a **local fine-tuned Kev**, with real-user capture and a continue-train loop.

[`slitherio/`](slitherio/) is a side piece: same pattern (harness + Kev + gold data + serve), pointed at a canvas game instead of generic web tasks.

## browser-agent (start here)

Flights / any URL+goal. Compare backends, collect gold, fine-tune, serve.

| piece | what |
|---|---|
| [`browser-agent/jev-ultrafast/`](browser-agent/jev-ultrafast/) | Harness + `--model jev\|kev` (default Kev `:8010`) |
| [`browser-agent/browser-capture/`](browser-agent/browser-capture/) | Chrome extension + local collector (`:8787`) |
| [`browser-agent/kev-finetune/`](browser-agent/kev-finetune/) | Convert capture dumps → train |
| [`browser-agent/kev/`](browser-agent/kev/) | Full Kev copy; drop/serve FT under `runs/browser-agent-ft*` |

```bash
cd browser-agent/jev-ultrafast
uv sync && cp .env.example .env   # OPENROUTER_API_KEY + TEXT_MODEL_API_KEY
uv run --env-file .env python examples/flights.py --model jev
# after teammate serves FT Kev on :8010:
uv run --env-file .env python examples/flights.py --model kev
```

Full loop (capture → convert → train → serve) is in [`browser-agent/README.md`](browser-agent/README.md).

## slitherio (same idea, different gym)

Human mouse gold + sensors + AIM policy. Already-shipped checkpoint at `slitherio/kev/runs/slither-ft-v2/` (**`:8009`** so it doesn’t collide with browser-agent).

See [`slitherio/README.md`](slitherio/README.md).
