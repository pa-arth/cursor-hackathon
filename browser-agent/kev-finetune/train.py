"""Fine-tune Kev on labelled browser decisions.

Lives at browser-agent/kev-finetune/. Imports the sibling browser-agent/kev
checkout (ROOT.parent / "kev"). Add pairs under data/inputs and data/outputs
(same filename), then from browser-agent/kev:

  uv run python ../kev-finetune/train.py --check
  uv run python ../kev-finetune/train.py --limit 1 --epochs 1 --accum 1 --out ../kev-finetune/weights/finetuned/smoke
  uv run python ../kev-finetune/train.py --out ../kev/runs/browser-agent-ft-v1

--init defaults to the Hub id jaredpalmer/kev-0.5b (read-only). --out must be
a new folder. Fine-tunes for the flights demo should land under
../kev/runs/browser-agent-ft* and be served on port 8010.

Each input is a TypeSafe /v1/systemone request (state + questions).
Each output maps question id -> chosen option key. Labels are option
keys, not free text.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from copy import deepcopy
from pathlib import Path

import torch

ROOT = Path(__file__).resolve().parent
KEV_ROOT = ROOT.parent / "kev"
DATA = ROOT / "data"
if not KEV_ROOT.is_dir():
    sys.exit(f"Expected the Kev repo at {KEV_ROOT}")
sys.path.insert(0, str(KEV_ROOT))

from kev.data import materialize  # noqa: E402
from kev.evaluate import load, resolve_run  # noqa: E402
from kev.train import question_loss  # noqa: E402


def load_pairs(data_dir: Path) -> list[dict]:
    inputs, outputs = data_dir / "inputs", data_dir / "outputs"
    if not inputs.is_dir() or not outputs.is_dir():
        raise SystemExit(f"Need {inputs} and {outputs}")
    records = []
    for path in sorted(inputs.glob("*.json")):
        out_path = outputs / path.name
        if not out_path.exists():
            raise SystemExit(f"Missing output file {out_path.name}")
        rec = json.loads(path.read_text())
        labels = json.loads(out_path.read_text())
        questions = rec.get("questions")
        if not isinstance(questions, dict) or not questions:
            raise SystemExit(f"{path.name}: questions must be a non-empty object")
        extra = set(labels) - set(questions)
        missing = set(questions) - set(labels)
        if extra or missing:
            raise SystemExit(f"{path.name}: label mismatch extra={sorted(extra)} missing={sorted(missing)}")
        source = rec.get("source", "browser")
        for qid, question in questions.items():
            choice = labels[qid]
            if question.get("type") == "choice" and choice not in question.get("criteria", {}):
                raise SystemExit(f"{path.name}: {qid} label {choice!r} is not in criteria")
            question["label"] = choice
            question["src"] = source
        rec["_meta"] = {"id": path.stem, "source": source}
        records.append(rec)
    if not records:
        raise SystemExit(f"No JSON files in {inputs}")
    return records


def shuffle_options(req: dict, rng: random.Random) -> dict:
    req = deepcopy(req)
    for question in req["questions"].values():
        if question.get("type") != "choice":
            continue
        keys = list(question["criteria"])
        rng.shuffle(keys)
        question["criteria"] = {key: question["criteria"][key] for key in keys}
    return req


def accuracy(tok, model, reqs) -> float:
    model.eval()
    ok = n = 0
    with torch.no_grad():
        for req in reqs:
            rec = materialize(req)
            logits = model.forward(model.encode(tok, rec, strict=True))
            for z, question in zip(logits, rec["questions"]):
                ok += int(int(z.argmax()) == question["label"])
                n += 1
    model.train()
    return ok / n if n else 0.0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=DATA, help="folder with inputs/ and outputs/")
    parser.add_argument("--init", default="jaredpalmer/kev-0.5b", help="existing Kev run or Hub id (read-only)")
    parser.add_argument("--out", type=Path, default=ROOT / "weights" / "finetuned" / "browser-sft")
    parser.add_argument("--epochs", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0, help="train on the first N examples only (0 = all)")
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--accum", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--device", choices=["cpu", "mps", "cuda"], default=None)
    parser.add_argument("--check", action="store_true", help="validate data only; do not load weights")
    args = parser.parse_args()

    reqs = load_pairs(args.data)
    if args.limit:
        reqs = reqs[: args.limit]
    for req in reqs:
        materialize(req)
    print(f"{len(reqs)} labelled requests from {args.data}: {[r['_meta']['id'] for r in reqs]}")
    if args.check:
        return

    if args.out.exists():
        raise SystemExit(f"refusing to overwrite {args.out}")
    device = args.device or (
        "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    )
    tok, model = load(args.init, device)
    model.train()
    opt = torch.optim.AdamW(model.trainable_parameters(), lr=args.lr, weight_decay=0.01)
    rng = random.Random(args.seed)
    torch.manual_seed(args.seed)

    t0 = time.time()
    step = seen = 0
    running = 0.0
    model.lm.config.use_cache = False
    for epoch in range(args.epochs):
        order = reqs[:]
        rng.shuffle(order)
        for req in order:
            rec = materialize(shuffle_options(req, rng))
            enc = model.encode(tok, rec, strict=True)
            logits = model.forward(enc)
            loss = sum(question_loss(z.float(), q, device, 0.0) for z, q in zip(logits, rec["questions"]))
            loss = loss / max(len(logits), 1) / args.accum
            if not torch.isfinite(loss):
                raise SystemExit("non-finite loss")
            loss.backward()
            running += loss.item() * args.accum
            seen += 1
            if seen % args.accum == 0:
                torch.nn.utils.clip_grad_norm_(model.trainable_parameters(), 1.0)
                opt.step()
                opt.zero_grad()
                step += 1
                print(f"ep{epoch} step {step} loss {running / args.accum:.3f} {(time.time() - t0) / seen:.3f}s/rec", flush=True)
                running = 0.0
        if seen % args.accum:
            torch.nn.utils.clip_grad_norm_(model.trainable_parameters(), 1.0)
            opt.step()
            opt.zero_grad()
            step += 1
        acc = accuracy(tok, model, reqs)
        print(f"ep{epoch} train_acc {acc:.3f}", flush=True)

    args.out.mkdir(parents=True)
    init_meta = torch.load(f"{resolve_run(args.init)}/head.pt", map_location="cpu")
    model.lm.save_pretrained(args.out)
    torch.save(
        {
            "head": model.head.state_dict(),
            "base": init_meta["base"],
            "base_revision": init_meta.get("base_revision"),
            "lora": init_meta.get("lora", 16),
            "head_dim": init_meta.get("head_dim", 256),
            "option_isolation": init_meta.get("option_isolation", False),
            "special_embeddings": init_meta.get("special_embeddings", False),
            "init": args.init,
            "examples": [r["_meta"]["id"] for r in reqs],
        },
        args.out / "head.pt",
    )
    tok.save_pretrained(args.out)
    print("saved", args.out)


if __name__ == "__main__":
    main()
