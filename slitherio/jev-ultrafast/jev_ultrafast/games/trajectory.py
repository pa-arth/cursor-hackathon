"""Log slither decisions as Kev/TypeSafe-style training records."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

# Keep state well under Kev's training max_state (384 tokens).
_DIR_ORDER = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")


def _dir_map(values: dict | None) -> str:
    values = values or {}
    return " ".join(f"{d}:{values.get(d, 0)}" for d in _DIR_ORDER)


def compact_game(game: dict | None) -> dict:
    """Unused structured form; prefer compact_state_text for training."""
    game = game or {}
    return {
        "len": game.get("length"),
        "hd": game.get("heading_dir"),
        "rec": game.get("recommended_dir"),
        "safe": game.get("safest_food_dir"),
        "clump": game.get("best_clump_dir"),
        "void": game.get("void_ahead"),
        "threat": game.get("nearest_threat_dist"),
    }


def compact_state_text(game: dict | None, goal: str | None = None) -> str:
    """Very compact sensor summary for Kev's 384-token state budget."""
    game = game or {}
    foods = game.get("nearest_foods") or []
    food_s = ",".join(
        f"{f.get('dir')}@{f.get('dist')}" for f in foods[:3] if isinstance(f, dict)
    ) or "-"
    snakes = game.get("nearby_snakes") or []
    snake_s = ",".join(
        f"{s.get('dir')}@{s.get('dist')}" for s in snakes[:2] if isinstance(s, dict)
    ) or "-"
    lines = [
        "slither",
        f"len={game.get('length')} hd={game.get('heading_dir')} rec={game.get('recommended_dir')} "
        f"safe={game.get('safest_food_dir')} clump={game.get('best_clump_dir')}@{game.get('best_clump_mass')} "
        f"void={int(bool(game.get('void_ahead')))} threat={game.get('nearest_threat_dist')}",
        f"safety {_dir_map(game.get('safety_score_by_direction'))}",
        f"threats {_dir_map(game.get('threat_pressure_by_direction'))}",
        f"food {food_s} snakes {snake_s}",
    ]
    return "\n".join(lines)


def compact_state_document(state) -> str:
    """Shrink a logged or live state blob so it fits Kev's 384-token state budget."""
    if isinstance(state, str):
        # Already compact text from a prior export.
        if state.startswith("slither\n") or state.startswith("slither "):
            return state
        try:
            parsed = json.loads(state)
        except json.JSONDecodeError:
            return state[:900]
    elif isinstance(state, dict):
        parsed = state
    else:
        return str(state)[:900]

    if isinstance(parsed, dict) and ("game" in parsed or "goal" in parsed or "alive" in parsed):
        game = parsed.get("game") if isinstance(parsed.get("game"), dict) else parsed
        return compact_state_text(game, parsed.get("goal") if isinstance(parsed, dict) else None)
    return compact_state_text(parsed if isinstance(parsed, dict) else {})


def _state_document(page: dict, goal: str) -> str:
    return compact_state_text(page.get("game") or {}, goal)


def aim_criteria(page: dict) -> dict[str, str]:
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
    criteria = {}
    for action in page.get("actions") or []:
        if action.get("kind") != "pointer":
            continue
        action_id = action["id"]
        criteria[action_id] = short_names.get(action_id, action.get("label") or action_id)
    return criteria


def make_aim_record(*, page: dict, goal: str, label: str, source: str, index: int = 0) -> dict | None:
    """One Choice question: which AIM/boost to take. `label` must be an action id."""
    criteria = aim_criteria(page)
    if len(criteria) < 2 or label not in criteria:
        return None
    state = _state_document(page, goal)
    record_id = f"{source}/train/{index:06d}"
    text_sha = hashlib.sha256(state.encode()).hexdigest()
    return {
        "state": state,
        "questions": {
            "aim": {
                "type": "choice",
                "instructions": (
                    "Given the slither.io sensor state and goal, choose the best AIM/boost action. "
                    "Prefer safe growth; avoid threats and void."
                ),
                "criteria": criteria,
                "label": label,
                "src": source,
            }
        },
        "_meta": {
            "id": record_id,
            "group_id": record_id,
            "source": source,
            "split": "train",
            "variant": "clean",
            "row": index,
            "text_sha256": text_sha,
            "length": (page.get("game") or {}).get("length"),
            "recommended_dir": (page.get("game") or {}).get("recommended_dir"),
            "ts": datetime.now(timezone.utc).isoformat(),
        },
    }


class TrajectoryLogger:
    def __init__(self, path: Path, source: str = "slither-agent"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.source = source
        self.count = 0

    def log_aim(self, *, page: dict, goal: str, label: str) -> bool:
        record = make_aim_record(
            page=page, goal=goal, label=label, source=self.source, index=self.count
        )
        if not record:
            return False
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.count += 1
        return True
