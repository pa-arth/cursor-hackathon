"""Local encrypted storage for the LLM API key.

On macOS the secret lives in the login Keychain (OS-encrypted).
Elsewhere it is AES-GCM encrypted under a 0600 master key file.
Episode trajectories are never stored here and never leave disk via these helpers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SERVICE = "browser-capture.local"
ACCOUNT = "llm-api-key"

ROOT = Path(__file__).resolve().parent.parent
SECRETS_DIR = Path(os.environ.get("CAPTURE_SECRETS_DIR", ROOT / "data" / "secrets"))
SETTINGS_PATH = SECRETS_DIR / "settings.json"
MASTER_KEY_PATH = SECRETS_DIR / "master.key"
API_KEY_PATH = SECRETS_DIR / "api_key.enc"

DEFAULT_SETTINGS = {
    "base_url": "https://openrouter.ai/api/v1",
    "model": "openai/gpt-4o-mini",
}


def _ensure_secrets_dir() -> None:
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(SECRETS_DIR, 0o700)
    except OSError:
        pass


def load_settings() -> dict:
    _ensure_secrets_dir()
    if not SETTINGS_PATH.exists():
        return dict(DEFAULT_SETTINGS)
    data = json.loads(SETTINGS_PATH.read_text())
    out = dict(DEFAULT_SETTINGS)
    out.update({k: v for k, v in data.items() if k in {"base_url", "model"}})
    return out


def save_settings(base_url: str | None = None, model: str | None = None) -> dict:
    _ensure_secrets_dir()
    current = load_settings()
    if base_url is not None:
        current["base_url"] = base_url.strip().rstrip("/") or DEFAULT_SETTINGS["base_url"]
    if model is not None:
        current["model"] = model.strip() or DEFAULT_SETTINGS["model"]
    SETTINGS_PATH.write_text(json.dumps(current, indent=2) + "\n")
    try:
        os.chmod(SETTINGS_PATH, 0o600)
    except OSError:
        pass
    return current


def _keychain_available() -> bool:
    return sys.platform == "darwin" and shutil_which("security") is not None


def shutil_which(cmd: str) -> str | None:
    from shutil import which

    return which(cmd)


def _keychain_set(api_key: str) -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
        capture_output=True,
        check=False,
    )
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-s",
            SERVICE,
            "-a",
            ACCOUNT,
            "-w",
            api_key,
            "-T",
            "",
            "-U",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "failed to store key in Keychain")


def _keychain_get() -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _keychain_delete() -> None:
    subprocess.run(
        ["security", "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
        capture_output=True,
        check=False,
    )


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError(
            "Install cryptography for encrypted API key storage off macOS: pip install cryptography"
        ) from exc
    _ensure_secrets_dir()
    if not MASTER_KEY_PATH.exists():
        MASTER_KEY_PATH.write_bytes(Fernet.generate_key())
        os.chmod(MASTER_KEY_PATH, 0o600)
    return Fernet(MASTER_KEY_PATH.read_bytes())


def _file_set(api_key: str) -> None:
    token = _fernet().encrypt(api_key.encode("utf-8"))
    API_KEY_PATH.write_bytes(token)
    os.chmod(API_KEY_PATH, 0o600)


def _file_get() -> str | None:
    if not API_KEY_PATH.exists():
        return None
    return _fernet().decrypt(API_KEY_PATH.read_bytes()).decode("utf-8")


def _file_delete() -> None:
    if API_KEY_PATH.exists():
        API_KEY_PATH.unlink()


def set_api_key(api_key: str) -> str:
    api_key = api_key.strip()
    if not api_key:
        raise ValueError("api key required")
    if _keychain_available():
        _keychain_set(api_key)
        _file_delete()
        return "keychain"
    _file_set(api_key)
    return "encrypted_file"


def get_api_key() -> str | None:
    if _keychain_available():
        key = _keychain_get()
        if key:
            return key
    return _file_get()


def clear_api_key() -> None:
    if _keychain_available():
        _keychain_delete()
    _file_delete()


def api_key_status() -> dict:
    key = get_api_key()
    backend = "none"
    if key:
        backend = "keychain" if (_keychain_available() and _keychain_get()) else "encrypted_file"
    settings = load_settings()
    return {
        "configured": bool(key),
        "backend": backend,
        "base_url": settings["base_url"],
        "model": settings["model"],
        # Never return the raw key.
        "hint": (key[:3] + "…" + key[-4:]) if key and len(key) > 8 else None,
    }


def suggest_intent(summary: dict) -> tuple[str, dict]:
    """Call the configured OpenAI-compatible chat API. Returns (intent, debug meta)."""
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("API key not configured")
    settings = load_settings()
    base_url = settings["base_url"].rstrip("/")
    model = settings["model"]

    steps = summary.get("steps") or []
    lines = []
    for step in steps[:80]:
        action = step.get("action") or {}
        bit = f"{step.get('step')}. {step.get('gesture')}"
        if action.get("kind"):
            bit += f" {action.get('kind')}"
        if action.get("label"):
            bit += f" [{action.get('label')[:120]}]"
        if action.get("text"):
            bit += f" text={action.get('text')[:80]!r}"
        if step.get("url"):
            bit += f" @ {step.get('url')[:100]}"
        lines.append(bit)

    user_prompt = (
        "Infer the user's single task goal from this browser trajectory.\n"
        "Return ONLY a concise imperative goal (one sentence, no quotes, no markdown).\n"
        f"Start URL: {summary.get('start_url') or 'unknown'}\n"
        f"Success flag: {summary.get('success')}\n"
        "Steps:\n"
        + ("\n".join(lines) if lines else "(no steps)")
    )

    import urllib.error
    import urllib.request

    payload = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You label browser-agent training episodes. "
                    "Write the goal the human was trying to accomplish."
                ),
            },
            {"role": "user", "content": user_prompt},
        ],
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://127.0.0.1:8787",
            "X-Title": "Browser Capture Local",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc

    intent = (
        ((body.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    ).strip()
    intent = intent.strip("\"'` ").splitlines()[0].strip() if intent else ""
    if not intent:
        raise RuntimeError("empty intent from model")
    meta = {
        "model": model,
        "base_url": base_url,
        "usage": body.get("usage"),
    }
    return intent, meta
