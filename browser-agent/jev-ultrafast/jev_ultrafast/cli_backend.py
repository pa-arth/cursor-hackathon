"""Shared CLI helpers for loading .env and selecting Jev vs local Kev."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from jev_ultrafast.model import DEFAULT_KEV_URL, configure_decision_backend


def load_env(path: Path | None = None) -> None:
    env_path = path or (Path.cwd() / ".env")
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))


def add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--model",
        choices=("jev", "kev"),
        default="jev",
        help="Decision backend: hosted Jev (OpenRouter) or local Kev System One (default: jev).",
    )
    parser.add_argument(
        "--kev-url",
        default=DEFAULT_KEV_URL,
        # TODO(team): change default when the browser-agent FT Kev is served from a known port/path.
        help=f"System One URL when --model kev (default: {DEFAULT_KEV_URL}).",
    )


def apply_model_arguments(args: argparse.Namespace) -> str:
    """Configure env from --model / --kev-url. Returns a short label for logging."""
    label = configure_decision_backend(args.model, kev_url=args.kev_url)
    if not os.environ.get("TEXT_MODEL_API_KEY"):
        print(
            "Note: TYPE_TEXT (typing into fields) still needs TEXT_MODEL_API_KEY in .env — "
            "that is a small helper LLM, not the Kev/Jev decision model. "
            "Copy jev-ultrafast/.env.example → .env and fill TEXT_MODEL_API_KEY "
            "(OpenRouter key is fine). --model kev does not need OPENROUTER_API_KEY.",
            flush=True,
        )
    return label
