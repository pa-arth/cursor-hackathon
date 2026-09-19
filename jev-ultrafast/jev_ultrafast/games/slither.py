"""Inject slither.io arena sensors into agent observations."""

from pathlib import Path

SENSE_JS = Path(__file__).with_name("slither_sense.js").read_text()
INSTALL_HUMAN_INTENT_JS = Path(__file__).with_name("human_intent.js").read_text()
READ_HUMAN_INTENT_JS = Path(__file__).with_name("read_human_intent.js").read_text()

DIRS = ("N", "NE", "E", "SE", "S", "SW", "W", "NW")
ID_TO_DIR = {
    "aim_n": "N",
    "aim_ne": "NE",
    "aim_e": "E",
    "aim_se": "SE",
    "aim_s": "S",
    "aim_sw": "SW",
    "aim_w": "W",
    "aim_nw": "NW",
}
DIR_TO_ID = {direction: action_id for action_id, direction in ID_TO_DIR.items()}


def install_human_intent(browser) -> None:
    browser.evaluate(INSTALL_HUMAN_INTENT_JS)


def read_human_intent(browser) -> dict | None:
    try:
        return browser.evaluate(READ_HUMAN_INTENT_JS)
    except Exception:
        return None


def human_aim_label(page: dict, intent: dict | None) -> str | None:
    """Map live mouse aim / boost onto an offered pointer action id (gold label)."""
    game = page.get("game") or {}
    if not game.get("alive"):
        return None
    ids = {a["id"] for a in page.get("actions") or [] if a.get("kind") == "pointer"}
    if not ids:
        return None
    intent = intent or {}
    if intent.get("boosting") and "boost" in ids:
        return "boost"
    direction = intent.get("dir") or game.get("heading_dir")
    action_id = DIR_TO_ID.get(direction) if direction else None
    if action_id in ids:
        return action_id
    return None


def format_game_text(game: dict) -> str:
    """Compact readable block so Jev sees score/food/threats in page text too."""
    if not game:
        return ""
    if game.get("alive") is False:
        return (
            f"[slither sensors]\nalive=False nickname={game.get('nickname')!r} "
            f"length={game.get('length')} — click Play Again once, then WAIT."
        )
    foods = ", ".join(
        f"{f['dir']}@{f['dist']}" for f in game.get("nearest_foods", [])[:6]
    ) or "none"
    clump = game.get("clump_mass_by_direction") or {}
    score = game.get("safety_score_by_direction") or {}
    clump_s = " ".join(f"{k}:{clump.get(k, 0)}" for k in DIRS)
    score_s = " ".join(f"{k}:{score.get(k, 0)}" for k in DIRS)
    threats = ", ".join(
        f"{t.get('name', '?')} {t['dir']}@{t['dist']} len={t['length']}"
        for t in game.get("nearby_snakes", [])[:5]
    ) or "none"
    return "\n".join(
        [
            "[slither sensors]",
            (
                f"alive={game.get('alive')} nickname={game.get('nickname')!r} "
                f"length/score_proxy={game.get('length')} heading={game.get('heading_dir')}"
                f"({game.get('heading_deg')}deg)"
            ),
            (
                f"recommended={game.get('recommended_dir')} safest_food={game.get('safest_food_dir')} "
                f"best_clump={game.get('best_clump_dir')}@{game.get('best_clump_mass')} "
                f"sticky={game.get('sticky_heading_dir')} "
                f"food_along_heading={game.get('food_along_heading')} "
                f"void_ahead={game.get('void_ahead')} "
                f"nearest_threat={game.get('nearest_threat_dist')}"
            ),
            f"clump_mass: {clump_s}",
            f"safety_score: {score_s}",
            f"nearest_foods: {foods}",
            f"nearby_snakes: {threats}",
            game.get("goal_hint") or "",
        ]
    )


def attach_slither_sensors(browser, page: dict, *, guardrails: bool = True) -> dict:
    """If in a live slither match, merge structured sensors into the page observation.

    guardrails=True hides UNSAFE AIM options when safer ones exist (demo seatbelts).
    guardrails=False keeps all AIMs so a decision model can learn avoidance itself.
    """
    url = (page.get("url") or "").lower()
    if "slither" not in url:
        return page
    try:
        game = browser.evaluate(SENSE_JS)
    except Exception:
        return page
    if not game:
        return page
    page = {**page, "game": game}
    block = format_game_text(game)
    text = page.get("text") or ""
    page["text"] = f"{block}\n{text}".strip()[:6000]

    if game.get("alive") is False:
        return page

    clump = game.get("clump_mass_by_direction") or {}
    threat = game.get("threat_pressure_by_direction") or {}
    void_p = game.get("void_pressure_by_direction") or {}
    safety = game.get("safety_score_by_direction") or {}
    nearest = game.get("nearest_foods") or []
    best = game.get("best_clump_dir")
    safest = game.get("safest_food_dir")
    recommended = game.get("recommended_dir")
    sticky = game.get("sticky_heading_dir")

    actions = []
    for action in page.get("actions") or []:
        action = dict(action)
        direction = ID_TO_DIR.get(action.get("id"))
        if action.get("kind") == "pointer" and direction:
            tpress = threat.get(direction, 0) or 0
            vpress = void_p.get(direction, 0) or 0
            unsafe = tpress >= 2.0 or vpress >= 0.9
            tags = []
            # Never advertise RECOMMENDED/SAFEST on an unsafe heading.
            if not unsafe and direction == recommended:
                tags.append("RECOMMENDED")
            if not unsafe and direction == safest:
                tags.append("SAFEST")
            if direction == best:
                tags.append("BEST_CLUMP")
            if direction == sticky:
                tags.append("STICKY")
            if unsafe:
                tags.append("UNSAFE")
            near = next((f for f in nearest if f.get("dir") == direction), None)
            near_s = f", nearest@{near['dist']}" if near else ""
            threat_s = f", threat={tpress}" if tpress else ""
            void_s = f", void={vpress}" if vpress else ""
            tag_s = f" [{' '.join(tags)}]" if tags else ""
            action["label"] = (
                f"Aim {direction} (clump={clump.get(direction, 0)}, "
                f"safe={safety.get(direction, 0)}{near_s}{threat_s}{void_s}){tag_s}"
            )
        elif action.get("id") == "boost":
            panic = game.get("nearest_threat_dist")
            if panic is not None and panic < 280:
                action["label"] = f"Boost AWAY (threat@{panic}, toward {recommended})"
            else:
                action["label"] = (
                    f"Boost toward {recommended} (length={game.get('length')}, "
                    f"food_ahead={game.get('food_along_heading')})"
                )
        actions.append(action)

    # Prefer safe AIMs only when guardrails are on.
    pointer = [a for a in actions if a.get("kind") == "pointer" and a.get("id") != "boost"]
    boost = [a for a in actions if a.get("id") == "boost"]
    other = [a for a in actions if a.get("kind") != "pointer"]
    if not guardrails:
        page["actions"] = actions
        return page
    safe_pointer = [a for a in pointer if "UNSAFE" not in a.get("label", "")]
    if safe_pointer:
        actions = other + safe_pointer + boost
    else:
        flee = [
            a
            for a in pointer
            if "RECOMMENDED" in a.get("label", "")
            or "SAFEST" in a.get("label", "")
            or ID_TO_DIR.get(a.get("id")) == recommended
        ]
        actions = other + (flee or pointer[:2]) + boost
    page["actions"] = actions
    return page
