#!/usr/bin/env python3
"""Local trajectory collector: extension → JSONL episodes on disk."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

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


def cors(handler: BaseHTTPRequestHandler) -> None:
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")


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
        path = urlparse(self.path).path
        if path in {"/", "/health"}:
            with _lock:
                n = len(list(DATA_DIR.glob("*/meta.json"))) if DATA_DIR.exists() else 0
            return self._json(200, {"ok": True, "episodes": n, "data_dir": str(DATA_DIR)})
        if path == "/v1/episodes":
            with _lock:
                episodes = []
                if DATA_DIR.exists():
                    for meta in sorted(DATA_DIR.glob("*/meta.json")):
                        episodes.append(read_json(meta, {}))
            return self._json(200, {"episodes": episodes})
        return self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            body = self._read_json()
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid json"})

        if path == "/v1/episodes":
            return self._start_episode(body)

        parts = path.strip("/").split("/")
        # /v1/episodes/{id}/steps | complete
        if len(parts) == 4 and parts[0] == "v1" and parts[1] == "episodes":
            episode_id = parts[2]
            if not EPISODE_ID.match(episode_id):
                return self._json(400, {"error": "invalid episode id"})
            if parts[3] == "steps":
                return self._append_step(episode_id, body)
            if parts[3] == "complete":
                return self._complete(episode_id, body)
        return self._json(404, {"error": "not found"})

    def _start_episode(self, body: dict) -> None:
        episode_id = str(body.get("id") or "").strip()
        intent = str(body.get("intent") or "").strip()
        if not EPISODE_ID.match(episode_id):
            return self._json(400, {"error": "id required (8-64 alnum/_/-)"})
        if not intent:
            return self._json(400, {"error": "intent required"})
        folder = episode_dir(episode_id)
        with _lock:
            if (folder / "meta.json").exists():
                return self._json(409, {"error": "episode already exists"})
            meta = {
                "id": episode_id,
                "intent": intent,
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
        with _lock:
            if not meta_path.exists():
                return self._json(404, {"error": "unknown episode"})
            meta = read_json(meta_path, {})
            if meta.get("status") != "recording":
                return self._json(409, {"error": "episode already completed"})
            meta["status"] = "complete"
            meta["success"] = body.get("success")
            meta["ended_at"] = utc_now()
            meta["notes"] = body.get("notes")
            write_json(meta_path, meta)
        return self._json(200, meta)


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[capture] listening on http://{HOST}:{PORT}", flush=True)
    print(f"[capture] writing episodes to {DATA_DIR}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[capture] stopped", flush=True)


if __name__ == "__main__":
    main()
