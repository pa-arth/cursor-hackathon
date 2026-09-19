"""Team demo / data collection for slither.io.

  # normal demo (Jev plays)
  uv run --env-file .env python examples/slither_demo.py --unlimited

  # GOLD: you play; we log your mouse aim as Kev labels
  uv run python examples/slither_demo.py --human

  # silver: sensor teacher labels
  uv run --env-file .env python examples/slither_demo.py --unlimited --record --teacher --no-guardrails

  # weak: whatever Jev chose
  uv run --env-file .env python examples/slither_demo.py --unlimited --record --no-guardrails
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import jev_ultrafast.browser as browser_mod

browser_mod.READ_STATE = Path(browser_mod.__file__).with_name("snapshot.js").read_text()
import jev_ultrafast.games.slither as slither_mod  # noqa: E402

slither_mod.SENSE_JS = Path(slither_mod.__file__).with_name("slither_sense.js").read_text()
slither_mod.INSTALL_HUMAN_INTENT_JS = Path(slither_mod.__file__).with_name("human_intent.js").read_text()
slither_mod.READ_HUMAN_INTENT_JS = Path(slither_mod.__file__).with_name("read_human_intent.js").read_text()

from browser_harness.helpers import cdp  # noqa: E402
from jev_ultrafast import Agent  # noqa: E402
from jev_ultrafast import agent as agent_mod  # noqa: E402
from jev_ultrafast import questions as questions_mod  # noqa: E402
from jev_ultrafast.browser import Browser  # noqa: E402
from jev_ultrafast.games.slither import (  # noqa: E402
    DIR_TO_ID,
    human_aim_label,
    install_human_intent,
    read_human_intent,
)
from jev_ultrafast.games.trajectory import TrajectoryLogger  # noqa: E402

UNLIMITED_STEPS = 10**9

DEFAULT_GOAL = (
    "Play slither.io. Type nickname '{nickname}', click Play, WAIT until Aim/Boost appear, "
    "then keep AIM-steering and boost to survive and grow. Prefer food, avoid walls/snakes when possible. "
    "Do NOT choose DONE or BLOCKED while still in-game. Only DONE if the snake died and the lobby returned."
)

HUMAN_GOAL = (
    "Human-played slither.io. Gold labels are the player's mouse aim octant (or boost while holding click/space)."
)


def load_env():
    path = Path.cwd() / ".env"
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def default_out_path(prefix: str = "run") -> Path:
    return Path("artifacts/slither-data") / (
        f"{prefix}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.jsonl"
    )


def run_human_recording(args) -> None:
    """You steer in Chrome; we sample sensors + your mouse aim into JSONL. No Jev calls."""
    os.environ["SLITHER_GUARDRAILS"] = "0"
    out = Path(args.out) if args.out else default_out_path("human")
    logger = TrajectoryLogger(out, source="slither-human")
    interval = max(0.05, 1.0 / max(args.hz, 0.1))
    goal = HUMAN_GOAL

    print("HUMAN RECORDING — you play, we label from your mouse.")
    print("  1. Focus the Chrome tab that just opened (slither.io).")
    print("  2. Enter a nick, click Play.")
    print("  3. Steer with the mouse; hold click or space to boost.")
    print("  4. Ctrl+C when done.\n")
    print(f"Sampling ~{args.hz:g} Hz → {out}")
    print("Guardrails: off (all AIM options stay in the choice set)\n")

    browser = Browser("http://slither.io/")
    started = time.perf_counter()
    last_label = None
    was_alive = False
    try:
        try:
            cdp("Target.activateTarget", targetId=browser.target)
        except Exception:
            pass
        install_human_intent(browser)

        while True:
            try:
                install_human_intent(browser)  # re-bind after lobby↔game navigations
                page = browser.observe(screenshot=False)
            except Exception as error:
                print(f"  (observe glitch: {error})")
                time.sleep(interval)
                continue

            game = page.get("game") or {}
            alive = bool(game.get("alive"))
            intent = read_human_intent(browser) if alive else None
            label = human_aim_label(page, intent) if alive else None

            if alive and not was_alive:
                print("  in-game — recording your moves")
            if was_alive and not alive:
                print(f"  died (len={game.get('length')}) — Play Again to keep recording")

            if alive and label:
                logged = logger.log_aim(page=page, goal=goal, label=label)
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                if logged and label != last_label:
                    boost = " BOOST" if label == "boost" else ""
                    print(
                        f"{elapsed_ms:>7} ms  n={logger.count:4}  human  {label}{boost}  "
                        f"len={game.get('length')}  mouse={intent.get('dir') if intent else '?'}"
                    )
                    last_label = label
                elif logged and logger.count % 20 == 0:
                    print(
                        f"{elapsed_ms:>7} ms  n={logger.count:4}  human  {label}  "
                        f"len={game.get('length')} (still recording…)"
                    )
            elif alive and not label:
                print("  (move the mouse over the game to start labeling)")

            was_alive = alive
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped — human recording complete.")
    finally:
        print(f"Recorded {logger.count} AIM examples → {logger.path}")
        browser.close()


parser = argparse.ArgumentParser(description="Run / record slither.io with Jev or human play.")
parser.add_argument("--max-actions", type=int, default=120)
parser.add_argument("--unlimited", action="store_true")
parser.add_argument("--nickname", default="JevBot")
parser.add_argument("--goal", default=None)
parser.add_argument(
    "--human",
    action="store_true",
    help="You play in Chrome; record mouse aim/boost as gold Kev labels (no Jev, no API key).",
)
parser.add_argument(
    "--hz",
    type=float,
    default=4.0,
    help="Samples per second in --human mode (default: 4).",
)
parser.add_argument(
    "--record",
    action="store_true",
    help="Append AIM decisions to artifacts/slither-data/*.jsonl for Kev fine-tuning.",
)
parser.add_argument(
    "--teacher",
    action="store_true",
    help="In-game: execute sensor recommended_dir instead of Jev (silver labels).",
)
parser.add_argument(
    "--guardrails",
    action=argparse.BooleanOptionalAction,
    default=True,
    help="Hide UNSAFE AIM options when safer ones exist (default: on; forced off for --human).",
)
parser.add_argument(
    "--out",
    default=None,
    help="JSONL path for recording (default: artifacts/slither-data/<prefix>-<timestamp>.jsonl).",
)
args = parser.parse_args()
load_env()

if args.human:
    if args.teacher:
        raise SystemExit("Use either --human or --teacher, not both.")
    run_human_recording(args)
    sys.exit(0)

os.environ["SLITHER_GUARDRAILS"] = "1" if args.guardrails else "0"

if args.unlimited or args.max_actions == 0:
    max_actions = UNLIMITED_STEPS
    print("Unlimited mode — Ctrl+C when you're happy.\n")
else:
    max_actions = args.max_actions

questions_mod.MAX_STEPS = max(max_actions, questions_mod.MAX_STEPS)
agent_mod.MAX_STEPS = questions_mod.MAX_STEPS

goal = (args.goal or DEFAULT_GOAL).format(nickname=args.nickname)
print(f"Goal: {goal}")
print(f"Guardrails: {'on' if args.guardrails else 'off'}")
if args.teacher:
    print("Teacher mode: in-game AIM follows recommended_dir (for training labels).")

logger = None
if args.record:
    out = Path(args.out) if args.out else default_out_path("run")
    source = "slither-teacher" if args.teacher else "slither-agent"
    logger = TrajectoryLogger(out, source=source)
    print(f"Recording to {out}\n")
else:
    print()

print("Starting slither demo — watch the Chrome tab. Ctrl+C when you're happy.\n")


def teacher_aim_id(page: dict) -> str | None:
    game = page.get("game") or {}
    if not game.get("alive"):
        return None
    direction = game.get("recommended_dir")
    if not direction:
        return None
    action_id = DIR_TO_ID.get(direction)
    ids = {a["id"] for a in page.get("actions") or [] if a.get("kind") == "pointer"}
    if action_id in ids:
        return action_id
    for action in page.get("actions") or []:
        if action.get("kind") == "pointer" and "RECOMMENDED" in (action.get("label") or ""):
            return action["id"]
    return None


with Agent("http://slither.io/", goal) as agent:
    try:
        cdp("Target.activateTarget", targetId=agent.browser.target)
    except Exception:
        pass
    try:
        while len(agent.state["history"]) < max_actions:
            page = agent.state["page"]
            in_game = bool((page.get("game") or {}).get("alive")) and any(
                a.get("kind") == "pointer" for a in page.get("actions") or []
            )

            if args.teacher and in_game:
                aim_id = teacher_aim_id(page)
                if aim_id:
                    action = next(a for a in page["actions"] if a["id"] == aim_id)
                    if logger:
                        logger.log_aim(page=page, goal=goal, label=aim_id)
                    try:
                        agent.state["browser"].act(action, page)
                        agent.state["history"].append(
                            {
                                "step": len(agent.state["history"]) + 1,
                                "action": action.get("label"),
                                "kind": action.get("kind"),
                                "choice": aim_id,
                                "operation": "AIM",
                                "target": aim_id,
                                "text": None,
                                "page_changed": None,
                            }
                        )
                        agent.state["page"] = agent.state["browser"].observe(screenshot=False)
                        agent.state["status"] = "ready"
                        agent.state["elapsed_ms"] = round(
                            (time.perf_counter() - (agent.state["started_at"] or time.perf_counter())) * 1000
                        )
                        if agent.state["started_at"] is None:
                            agent.state["started_at"] = time.perf_counter()
                        print(
                            f"{agent.state['elapsed_ms']:>6} ms  n={len(agent.state['history']):3}  "
                            f"teacher   {action.get('label')}"
                        )
                        continue
                    except Exception as error:
                        print(f"  (teacher act failed: {error})")

            page_before = agent.state["page"]
            try:
                if agent.state["started_at"] is None:
                    agent.state["started_at"] = time.perf_counter()
                state = agent.command("tick")
            except (ValueError, RuntimeError) as error:
                message = str(error)
                if "demo budget" in message or "model-call budget" in message:
                    print(f"\nHit built-in agent budget ({message}).")
                    break
                print(f"  (retry after model/browser glitch: {error})")
                agent.state["decision"] = None
                agent.state["status"] = "ready"
                try:
                    agent.state["page"] = agent.state["browser"].observe(screenshot=False)
                except Exception:
                    pass
                continue

            last = state["history"][-1] if state["history"] else None
            if logger and last and last.get("operation") == "AIM" and last.get("choice"):
                logger.log_aim(page=page_before, goal=goal, label=last["choice"])

            detail = f"{last.get('operation')} {last.get('action')}" if last else ""
            print(
                f"{state['elapsed_ms']:>6} ms  n={len(state['history']):3}  {state['status']:8}  {detail}".rstrip()
            )

            if last and "Play Again" in str(last.get("action") or ""):
                recent = state["history"][-4:]
                if sum(1 for h in recent if "Play Again" in str(h.get("action") or "")) >= 2:
                    print("  (cooldown after Play Again)")
                    try:
                        time.sleep(1.2)
                        agent.state["page"] = agent.state["browser"].observe(screenshot=False)
                        agent.state["decision"] = None
                        agent.state["status"] = "ready"
                    except Exception:
                        pass

            if state["status"] in {"done", "blocked"}:
                actions = state["page"]["actions"]
                has_aim = any(a.get("kind") == "pointer" for a in actions)
                play_again = any("Play Again" in str(a.get("label") or "") for a in actions)
                if has_aim and not play_again and len(state["history"]) < max_actions:
                    print("  (Jev wanted to stop; demo keep-going while Aim controls remain)")
                    agent.state["status"] = "ready"
                    agent.state["decision"] = None
                    continue
                break
    except KeyboardInterrupt:
        print("\nStopped by you — demo complete.")
        if logger:
            print(f"Recorded {logger.count} AIM examples → {logger.path}")
        sys.exit(0)

print(f"\nFinished after {len(agent.state['history'])} actions ({agent.state['status']}).")
if logger:
    print(f"Recorded {logger.count} AIM examples → {logger.path}")
