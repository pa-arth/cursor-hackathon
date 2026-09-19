"""Convert browser-capture JSON into kev-finetune input/output pairs.

Uses jev-ultrafast's action_space() so option keys match live inference
(indexes like "2", not capture ids like "e4"). Typed strings are dropped;
Kev only learns operation + target.

  ../kev/.venv/bin/python convert_capture.py
  ../kev/.venv/bin/python train.py --check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JEV_ROOT = ROOT.parent / "jev-ultrafast"
if not JEV_ROOT.is_dir():
    sys.exit(f"Expected jev-ultrafast at {JEV_ROOT}")


def _load_questions():
    import importlib.util

    path = JEV_ROOT / "jev_ultrafast" / "questions.py"
    spec = importlib.util.spec_from_file_location("jev_questions", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.NEXT_ACTION, module.TARGET


NEXT_ACTION, TARGET = _load_questions()


def action_space(actions):
    """Keep in sync with jev_ultrafast.model.action_space."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {k: action[k] for k in ("role", "value", "checked", "selected", "expanded") if k in action}
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls

KIND_TO_OP = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
OP_HELP = {
    "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
    "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
    "SELECT": "Select an observed dropdown value.",
}


def load_examples(path: Path) -> list[dict]:
    payload = json.loads(path.read_text())
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict) and isinstance(payload.get("examples"), list):
        return payload["examples"]
    raise SystemExit(f"{path.name}: expected a capture object with examples[] or a list")


def history_for_kev(history: list[dict]) -> list[dict]:
    return [
        {
            "action": item.get("label") or item.get("action"),
            "kind": item.get("kind"),
            "text": item.get("text"),
            "page_changed": item.get("page_changed"),
        }
        for item in history[-10:]
    ]


def convert_example(example: dict) -> tuple[dict, dict]:
    observation = example["observation"]
    chosen = example.get("action") or {}
    chosen_id = chosen.get("id") or (example.get("completion") or {}).get("action_id")
    if not chosen_id:
        raise ValueError("missing chosen action id")
    actions = observation["actions"]
    match = next((item for item in actions if item["id"] == chosen_id), None)
    if match is None:
        raise ValueError(f"chosen id {chosen_id!r} not in observation actions")
    elements, targets, controls = action_space(actions)
    kind = match["kind"]
    if kind in KIND_TO_OP:
        operation = KIND_TO_OP[kind]
        if operation not in targets:
            raise ValueError(f"{operation} not available in action space")
        target = next((index for index, item in targets[operation].items() if item["id"] == chosen_id), None)
        if target is None:
            raise ValueError(f"{chosen_id!r} has no {operation} index")
        labels = {"operation": operation, f"{operation.lower()}_target": target}
    else:
        operation = match["id"].upper()
        if operation not in controls:
            raise ValueError(f"unmapped control {match['id']!r} kind={kind!r}")
        labels = {"operation": operation}

    operations = {key: OP_HELP[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(DONE="Every requirement is visibly satisfied.", BLOCKED="No supported operation can progress.")
    goal = example.get("intent") or (example.get("prompt") or {}).get("goal") or ""
    questions = {
        "operation": {
            "type": "choice",
            "criteria": operations,
            "instructions": {"goal": goal, "rules": NEXT_ACTION},
        }
    }
    if operation in targets:
        candidates = targets[operation]
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {item['label']}",
                    "current_value": item.get("current_value", item.get("value", "")),
                    **{key: item[key] for key in ("role", "checked", "selected", "expanded") if key in item},
                }
                for index, item in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    inp = {
        "source": "capture",
        "state": {
            "page": {key: observation.get(key, "") for key in ("url", "title", "text")},
            "elements": elements,
            "recent_actions": history_for_kev(example.get("history") or []),
        },
        "questions": questions,
    }
    return inp, labels


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=ROOT / "potential_data")
    parser.add_argument("--out", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    files = sorted([*args.src.glob("*.json"), *args.src.glob("*.txt")])
    if not files:
        raise SystemExit(f"No capture files in {args.src}")

    inputs_dir, outputs_dir = args.out / "inputs", args.out / "outputs"
    inputs_dir.mkdir(parents=True, exist_ok=True)
    outputs_dir.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for path in files:
        for example in load_examples(path):
            name = f"capture-{example.get('episode_id', 'ep')[:8]}-step{int(example.get('step', 0)):02d}.json"
            try:
                inp, labels = convert_example(example)
            except (KeyError, ValueError) as exc:
                skipped += 1
                print(f"skip {name}: {exc}")
                continue
            (inputs_dir / name).write_text(json.dumps(inp, indent=2) + "\n")
            (outputs_dir / name).write_text(json.dumps(labels, indent=2) + "\n")
            written += 1
    print(f"wrote {written} pairs to {args.out} (skipped {skipped})")


if __name__ == "__main__":
    main()
