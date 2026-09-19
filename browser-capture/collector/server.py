#!/usr/bin/env python3
"""Local trajectory collector: extension → JSONL episodes on disk.

Episode data stays on this machine. The only optional outbound call is intent
suggestion to the user-configured LLM endpoint (step summary only).
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


# Allow `python collector/server.py` to import sibling modules
sys.path.insert(0, str(Path(__file__).resolve().parent))
from credential_store import (  # noqa: E402
    api_key_status,
    clear_api_key,
    get_api_key,
    load_settings,
    save_settings,
    set_api_key,
    suggest_intent,
)

HOST = os.environ.get("CAPTURE_HOST", "127.0.0.1")
PORT = int(os.environ.get("CAPTURE_PORT", "8787"))
DATA_DIR = Path(
    os.environ.get(
        "CAPTURE_DATA_DIR",
        Path(__file__).resolve().parent.parent / "data" / "episodes",
    )
)

EPISODE_ID = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")
_lock = threading.Lock()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def episode_dir(episode_id: str) -> Path:
    return DATA_DIR / episode_id


def read_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def read_steps(episode_id: str) -> list:
    path = episode_dir(episode_id) / "steps.jsonl"
    if not path.exists():
        return []
    steps = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            steps.append(json.loads(line))
    return steps


def list_episode_ids() -> list[str]:
    if not DATA_DIR.exists():
        return []
    ids = []
    for meta in sorted(DATA_DIR.glob("*/meta.json")):
        ids.append(meta.parent.name)
    return ids


def load_episode(episode_id: str) -> dict | None:
    meta_path = episode_dir(episode_id) / "meta.json"
    if not meta_path.exists():
        return None
    meta = read_json(meta_path, {})
    steps = read_steps(episode_id)
    return {"meta": meta, "steps": steps}


def format_action_space(actions: list | None) -> str:
    """Compact indexed table matching jev-style training prompts."""
    lines = []
    for action in actions or []:
        kind = action.get("kind") or "?"
        label = (action.get("label") or "").strip()
        value = action.get("value")
        aid = action.get("id") or "?"
        role = action.get("role") or ""
        extra = ""
        if value not in (None, ""):
            extra = f" · {value}"
        role_bit = f"{role:10}" if role else " " * 10
        lines.append(f"[{aid}] {kind:6} {role_bit} {label}{extra}".rstrip())
    return "\n".join(lines)


def slim_action(action: dict | None) -> dict | None:
    if not action:
        return None
    out = {
        "id": action.get("id"),
        "kind": action.get("kind"),
        "label": action.get("label"),
        "node": action.get("node"),
        "role": action.get("role"),
    }
    if action.get("text") is not None:
        out["text"] = action.get("text")
    if action.get("value") not in (None, ""):
        out["value"] = action.get("value")
    if action.get("delta") is not None:
        out["delta"] = action.get("delta")
    return out


def training_observation(observation: dict | None) -> dict | None:
    if not observation:
        return None
    actions = observation.get("actions") or []
    return {
        "url": observation.get("url"),
        "title": observation.get("title"),
        "text": observation.get("text") or "",
        "scroll": observation.get("scroll"),
        "w": observation.get("w"),
        "h": observation.get("h"),
        "omitted_actions": observation.get("omitted_actions") or 0,
        "actions": actions,
        "action_space": format_action_space(actions),
    }


def build_training_example(meta: dict, step: dict, history: list) -> dict | None:
    """One supervised row: goal + observation (indexed elements) + discrete action."""
    if not step.get("mapped", True):
        return None
    action = slim_action(step.get("action"))
    if not action or not action.get("id") or not action.get("kind"):
        return None
    observation = training_observation(step.get("observation"))
    if not observation or not observation.get("actions"):
        return None
    # Target must exist in the observed action space (aligns train ↔ serve).
    ids = {a.get("id") for a in observation["actions"]}
    if action["id"] not in ids:
        return None
    return {
        "episode_id": meta.get("id"),
        "intent": meta.get("intent") or "",
        "intent_source": meta.get("intent_source"),
        "success": meta.get("success"),
        "step": step.get("step"),
        "ts": step.get("ts"),
        "gesture": step.get("gesture"),
        "history": history,
        "observation": observation,
        "action": action,
        # Ready-to-pack SFT fields for browser / computer-use policies.
        "prompt": {
            "goal": meta.get("intent") or "",
            "url": observation.get("url"),
            "page_text": observation.get("text"),
            "action_space": observation.get("action_space"),
            "history": history,
        },
        "completion": {
            "action_id": action["id"],
            "kind": action["kind"],
            "text": action.get("text"),
        },
    }


def build_dataset(*, mapped_only: bool = True, success_only: bool = False, complete_only: bool = True) -> dict:
    episodes = []
    examples = []
    skipped = {"unmapped": 0, "incomplete": 0, "unsuccessful": 0, "invalid": 0}

    for episode_id in list_episode_ids():
        loaded = load_episode(episode_id)
        if not loaded:
            continue
        meta = loaded["meta"]
        steps = loaded["steps"]

        if complete_only and meta.get("status") != "complete":
            skipped["incomplete"] += 1
            continue
        if success_only and meta.get("success") is not True:
            skipped["unsuccessful"] += 1
            continue

        history = []
        episode_examples = []
        for step in steps:
            if mapped_only and not step.get("mapped", True):
                skipped["unmapped"] += 1
                continue
            example = build_training_example(meta, step, list(history))
            if not example:
                skipped["invalid"] += 1
                continue
            episode_examples.append(example)
            examples.append(example)
            history.append(
                {
                    "step": example["step"],
                    "kind": example["action"]["kind"],
                    "id": example["action"]["id"],
                    "label": example["action"].get("label"),
                    "text": example["action"].get("text"),
                }
            )

        episodes.append(
            {
                **meta,
                "steps": steps,
                "training_examples": episode_examples,
                "training_example_count": len(episode_examples),
            }
        )

    return {
        "schema": "browser-capture.element_grounded.v1",
        "description": (
            "Element-grounded browser trajectories for local fine-tuning. "
            "Each training example is (goal, indexed action_space, history) → "
            "(action_id, kind, text). Prefer mapped steps from successful episodes."
        ),
        "counts": {
            "episodes": len(episodes),
            "raw_steps": sum(len(e.get("steps") or []) for e in episodes),
            "training_examples": len(examples),
            "skipped": skipped,
        },
        "episodes": episodes,
        "examples": examples,
    }


def cors(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


def query_flag(qs: dict, name: str, default: bool) -> bool:
    values = qs.get(name)
    if not values:
        return default
    return str(values[0]).lower() in {"1", "true", "yes", "on"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[capture] {self.address_string()} {fmt % args}", flush=True)

    def _json(self, code: int, payload) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        cors(self)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode() or "{}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        cors(self)
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in {"/", "/health"}:
            with _lock:
                n = len(list(DATA_DIR.glob("*/meta.json"))) if DATA_DIR.exists() else 0
            status = api_key_status()
            return self._json(
                200,
                {
                    "ok": True,
                    "episodes": n,
                    "data_dir": str(DATA_DIR),
                    "api_key_configured": status["configured"],
                    "api_key_backend": status["backend"],
                    "dataset": "http://127.0.0.1:8787/v1/dataset",
                },
            )
        if path == "/v1/dataset":
            with _lock:
                payload = build_dataset(
                    mapped_only=query_flag(qs, "mapped_only", True),
                    success_only=query_flag(qs, "success_only", False),
                    complete_only=query_flag(qs, "complete_only", True),
                )
            return self._json(200, payload)
        if path == "/v1/examples":
            with _lock:
                payload = build_dataset(
                    mapped_only=query_flag(qs, "mapped_only", True),
                    success_only=query_flag(qs, "success_only", True),
                    complete_only=query_flag(qs, "complete_only", True),
                )
            return self._json(
                200,
                {
                    "schema": payload["schema"],
                    "counts": payload["counts"],
                    "examples": payload["examples"],
                },
            )
        if path == "/v1/episodes":
            include_steps = query_flag(qs, "include_steps", False)
            with _lock:
                episodes = []
                for episode_id in list_episode_ids():
                    loaded = load_episode(episode_id)
                    if not loaded:
                        continue
                    if include_steps:
                        episodes.append({**loaded["meta"], "steps": loaded["steps"]})
                    else:
                        episodes.append(loaded["meta"])
            return self._json(200, {"episodes": episodes})
        if path == "/v1/settings":
            return self._json(200, api_key_status())

        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "v1" and parts[1] == "episodes":
            episode_id = parts[2]
            if not EPISODE_ID.match(episode_id):
                return self._json(400, {"error": "invalid episode id"})
            with _lock:
                loaded = load_episode(episode_id)
            if not loaded:
                return self._json(404, {"error": "unknown episode"})
            return self._json(200, {**loaded["meta"], "steps": loaded["steps"]})

        return self._json(404, {"error": "not found"})

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/settings/api-key":
            clear_api_key()
            return self._json(200, api_key_status())
        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})

        if path == "/v1/episodes":
            return self._start_episode(body)
        if path == "/v1/settings":
            return self._save_settings(body)
        if path == "/v1/settings/api-key":
            return self._save_api_key(body)
        if path == "/v1/suggest-intent":
            return self._suggest_from_body(body)

        parts = path.strip("/").split("/")
        # /v1/episodes/{id}/steps | complete | suggest-intent
        if len(parts) == 4 and parts[0] == "v1" and parts[1] == "episodes":
            episode_id = parts[2]
            if not EPISODE_ID.match(episode_id):
                return self._json(400, {"error": "invalid episode id"})
            if parts[3] == "steps":
                return self._append_step(episode_id, body)
            if parts[3] == "complete":
                return self._complete(episode_id, body)
            if parts[3] == "suggest-intent":
                return self._suggest_episode(episode_id, body)
        return self._json(404, {"error": "not found"})

    def _save_settings(self, body: dict) -> None:
        settings = save_settings(base_url=body.get("base_url"), model=body.get("model"))
        status = api_key_status()
        status.update(settings)
        return self._json(200, status)

    def _save_api_key(self, body: dict) -> None:
        try:
            backend = set_api_key(str(body.get("api_key") or ""))
            if body.get("base_url") is not None or body.get("model") is not None:
                save_settings(base_url=body.get("base_url"), model=body.get("model"))
        except Exception as exc:
            return self._json(400, {"error": str(exc)})
        status = api_key_status()
        status["saved_backend"] = backend
        return self._json(200, status)

    def _suggest_from_body(self, body: dict) -> None:
        try:
            intent, meta = suggest_intent(body)
        except Exception as exc:
            return self._json(400, {"error": str(exc)})
        return self._json(200, {"intent": intent, "meta": meta, "intent_source": "llm"})

    def _suggest_episode(self, episode_id: str, body: dict) -> None:
        folder = episode_dir(episode_id)
        meta_path = folder / "meta.json"
        with _lock:
            if not meta_path.exists():
                return self._json(404, {"error": "unknown episode"})
            meta = read_json(meta_path, {})
            steps = read_steps(episode_id)
        summary = {
            "start_url": meta.get("start_url"),
            "success": body.get("success", meta.get("success")),
            "steps": [
                {
                    "step": s.get("step"),
                    "gesture": s.get("gesture"),
                    "url": s.get("url"),
                    "mapped": s.get("mapped"),
                    "action": {
                        "kind": (s.get("action") or {}).get("kind"),
                        "label": (s.get("action") or {}).get("label"),
                        "text": (s.get("action") or {}).get("text"),
                    },
                }
                for s in steps
                if s.get("mapped", True)
            ],
        }
        try:
            intent, llm_meta = suggest_intent(summary)
        except Exception as exc:
            return self._json(400, {"error": str(exc)})
        return self._json(200, {"intent": intent, "meta": llm_meta, "intent_source": "llm"})

    def _start_episode(self, body: dict) -> None:
        episode_id = str(body.get("id") or "").strip()
        intent = str(body.get("intent") or "").strip()
        if not EPISODE_ID.match(episode_id):
            return self._json(400, {"error": "id required (8-64 alnum/_/-)"})
        folder = episode_dir(episode_id)
        with _lock:
            if (folder / "meta.json").exists():
                return self._json(409, {"error": "episode already exists"})
            meta = {
                "id": episode_id,
                "intent": intent,
                "intent_source": "human" if intent else "pending",
                "source": body.get("source") or "human_extension",
                "start_url": body.get("start_url"),
                "allowlist": body.get("allowlist") or [],
                "status": "recording",
                "success": None,
                "step_count": 0,
                "started_at": utc_now(),
                "ended_at": None,
            }
            write_json(folder / "meta.json", meta)
            (folder / "steps.jsonl").write_text("")
        return self._json(201, meta)

    def _append_step(self, episode_id: str, body: dict) -> None:
        folder = episode_dir(episode_id)
        meta_path = folder / "meta.json"
        with _lock:
            if not meta_path.exists():
                return self._json(404, {"error": "unknown episode"})
            meta = read_json(meta_path, {})
            if meta.get("status") != "recording":
                return self._json(409, {"error": "episode not recording"})
            step_idx = int(meta.get("step_count") or 0) + 1
            step = {
                "step": step_idx,
                "ts": body.get("ts") or utc_now(),
                "url": body.get("url"),
                "mapped": bool(body.get("mapped", True)),
                "observation": body.get("observation"),
                "action": body.get("action"),
                "gesture": body.get("gesture"),
            }
            with (folder / "steps.jsonl").open("a") as f:
                f.write(json.dumps(step, ensure_ascii=False) + "\n")
            meta["step_count"] = step_idx
            write_json(meta_path, meta)
        return self._json(200, {"ok": True, "step": step_idx})

    def _complete(self, episode_id: str, body: dict) -> None:
        folder = episode_dir(episode_id)
        meta_path = folder / "meta.json"
        suggest = body.get("suggest_intent", True)
        provided = str(body.get("intent") or "").strip()

        with _lock:
            if not meta_path.exists():
                return self._json(404, {"error": "unknown episode"})
            meta = read_json(meta_path, {})
            if meta.get("status") != "recording":
                return self._json(409, {"error": "episode already completed"})
            steps = read_steps(episode_id)

        intent = provided or str(meta.get("intent") or "").strip()
        intent_source = meta.get("intent_source") or ("human" if intent else "pending")
        suggest_error = None
        llm_meta = None

        if suggest and not intent:
            summary = {
                "start_url": meta.get("start_url"),
                "success": body.get("success"),
                "steps": [
                    {
                        "step": s.get("step"),
                        "gesture": s.get("gesture"),
                        "url": s.get("url"),
                        "mapped": s.get("mapped"),
                        "action": {
                            "kind": (s.get("action") or {}).get("kind"),
                            "label": (s.get("action") or {}).get("label"),
                            "text": (s.get("action") or {}).get("text"),
                        },
                    }
                    for s in steps
                    if s.get("mapped", True)
                ],
            }
            try:
                intent, llm_meta = suggest_intent(summary)
                intent_source = "llm"
            except Exception as exc:
                suggest_error = str(exc)
                intent_source = "missing"

        if provided:
            intent_source = "human"

        with _lock:
            meta = read_json(meta_path, {})
            if meta.get("status") != "recording":
                return self._json(409, {"error": "episode already completed"})
            meta["status"] = "complete"
            meta["success"] = body.get("success")
            meta["ended_at"] = utc_now()
            meta["notes"] = body.get("notes")
            meta["intent"] = intent
            meta["intent_source"] = intent_source
            if llm_meta:
                meta["intent_model"] = llm_meta
            if suggest_error:
                meta["intent_suggest_error"] = suggest_error
            write_json(meta_path, meta)

        out = dict(meta)
        if suggest_error and not intent:
            out["warning"] = suggest_error
        return self._json(200, out)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[capture] listening on http://{HOST}:{PORT}", flush=True)
    print(f"[capture] writing episodes to {DATA_DIR}", flush=True)
    print(f"[capture] api key configured: {bool(get_api_key())}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[capture] stopped", flush=True)


if __name__ == "__main__":
    main()
