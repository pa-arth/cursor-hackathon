"""Merge recorded slither JSONL runs into a Kev-trainablesuite.

  uv run python examples/export_slither_suite.py \\
      --in artifacts/slither-data \\
      --out artifacts/slither-suite

Then fine-tune (from the kev/ checkout):

  uv run python -m kev.train \\
      --suite ../jev-ultrafast/artifacts/slither-suite \\
      --base Qwen/Qwen2.5-0.5B \\
      --base_revision 060db6499f32faf8b98477b0a26969ef7d8b9987 \\
      --epochs 2 --lr 5e-5 --accum 4 --out runs/slither-ft
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jev_ultrafast.games.trajectory import compact_state_document  # noqa: E402


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def load_jsonl(path: Path) -> list[dict]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def normalize(record: dict, index: int, source_fallback: str) -> dict | None:
    questions = record.get("questions") or {}
    aim = questions.get("aim")
    if not aim or aim.get("type") != "choice":
        return None
    criteria = aim.get("criteria") or {}
    label = aim.get("label")
    if len(criteria) < 2 or label not in criteria:
        return None
    source = aim.get("src") or (record.get("_meta") or {}).get("source") or source_fallback
    record_id = f"{source}/train/{index:06d}"
    state = compact_state_document(record["state"])
    # Criteria text is redundant with state sensors — keep short option names.
    short_names = {
        "aim_n": "Aim N",
        "aim_ne": "Aim NE",
        "aim_e": "Aim E",
        "aim_se": "Aim SE",
        "aim_s": "Aim S",
        "aim_sw": "Aim SW",
        "aim_w": "Aim W",
        "aim_nw": "Aim NW",
        "boost": "Boost",
    }
    short_criteria = {key: short_names.get(key, str(key)) for key in criteria}
    text_sha = hashlib.sha256(state.encode()).hexdigest()
    meta = dict(record.get("_meta") or {})
    meta.update(
        {
            "id": record_id,
            "group_id": record_id,
            "source": source,
            "split": "train",
            "variant": "clean",
            "row": index,
            "text_sha256": text_sha,
        }
    )
    return {
        "state": state,
        "questions": {
            "aim": {
                "type": "choice",
                "instructions": (
                    "Given the slither.io sensor state, choose the best AIM/boost action. "
                    "Prefer safe growth; avoid threats and void."
                ),
                "criteria": short_criteria,
                "label": label,
                "src": source,
            }
        },
        "_meta": meta,
    }


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


parser = argparse.ArgumentParser(description="Build a Kev suite from slither trajectory JSONL.")
parser.add_argument("--in", dest="inp", default="artifacts/slither-data", help="File or directory of *.jsonl runs")
parser.add_argument("--out", default="artifacts/slither-suite", help="Suite directory to write")
parser.add_argument("--calib-frac", type=float, default=0.1)
parser.add_argument("--dev-frac", type=float, default=0.1)
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--min-train", type=int, default=20, help="Refuse to export if train split is smaller")
args = parser.parse_args()

inp = Path(args.inp)
paths = [inp] if inp.is_file() else sorted(inp.glob("*.jsonl"))
if not paths:
    raise SystemExit(f"No JSONL files under {inp}")

raw: list[dict] = []
for path in paths:
    raw.extend(load_jsonl(path))

records = []
for index, record in enumerate(raw):
    normalized = normalize(record, index, source_fallback="slither")
    if normalized:
        records.append(normalized)

if not records:
    raise SystemExit("No valid AIM choice records found.")

rng = random.Random(args.seed)
rng.shuffle(records)
n = len(records)
n_dev = max(1, int(round(n * args.dev_frac))) if n >= 10 else 0
n_cal = max(1, int(round(n * args.calib_frac))) if n >= 10 else 0
dev = records[:n_dev]
cal = records[n_dev : n_dev + n_cal]
train = records[n_dev + n_cal :]
if len(train) < args.min_train:
    raise SystemExit(
        f"Only {len(train)} train records after split (need --min-train {args.min_train}). "
        f"Record more with: uv run --env-file .env python examples/slither_demo.py "
        f"--unlimited --record --teacher --no-guardrails"
    )

out = Path(args.out)
out.mkdir(parents=True, exist_ok=True)
write_jsonl(out / "train.jsonl", train)
write_jsonl(out / "calibration.jsonl", cal or train[: min(5, len(train))])
write_jsonl(out / "development.jsonl", dev or train[: min(5, len(train))])

sources = sorted({r["_meta"]["source"] for r in train})
files = {}
for name in ("train.jsonl", "calibration.jsonl", "development.jsonl"):
    path = out / name
    files[name] = {
        "sha256": digest(path),
        "records": sum(1 for _ in path.open(encoding="utf-8") if _.strip()),
    }

manifest = {
    "version": 1,
    "seed": args.seed,
    "holdout_sources": [],
    "trainable_sources": sources,
    "eval_only_sources": [],
    "base_revisions": {
        "Qwen/Qwen2.5-0.5B": "060db6499f32faf8b98477b0a26969ef7d8b9987",
        "Qwen/Qwen3-0.6B-Base": "da87bfb608c14b7cf20ba1ce41287e8de496c0cd",
    },
    "files": files,
    "context": {
        "task": "slither-aim",
        "notes": "Prefer slither-human (gold mouse labels); teacher/agent are silver/weak.",
    },
}
kev_manifest = Path(__file__).resolve().parents[2] / "kev" / "evals" / "decision-v1" / "manifest.json"
if kev_manifest.exists():
    pinned = json.loads(kev_manifest.read_text()).get("base_revisions") or {}
    manifest["base_revisions"].update(pinned)

(out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
print(f"Wrote suite → {out}")
print(f"  train={files['train.jsonl']['records']}  calib={files['calibration.jsonl']['records']}  "
      f"dev={files['development.jsonl']['records']}")
print(f"  sources={sources}")
print(
    "\nTrain with:\n"
    f"  cd ../kev && uv run python -m kev.train --suite {out.resolve()} "
    f"--base Qwen/Qwen2.5-0.5B --epochs 2 --lr 5e-5 --accum 4 --out runs/slither-ft"
)
