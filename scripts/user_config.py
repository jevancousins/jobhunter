"""Shared loader for the user's pipeline configuration.

All user-specific tuning (search targets, filters, autonomy level, right-to-work
model) lives in data/search_config.json, created from data/search_config.example.json
by the /onboard skill. Code must never fall back to hardcoded personal values.
"""

from __future__ import annotations

import json
import sys
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "data" / "search_config.json"
EXAMPLE_PATH = PROJECT_ROOT / "data" / "search_config.example.json"


class ConfigError(SystemExit):
    pass


@lru_cache(maxsize=1)
def load_search_config() -> dict:
    """Load data/search_config.json, exiting with guidance if it is missing."""
    if not CONFIG_PATH.exists():
        raise ConfigError(
            "data/search_config.json not found.\n"
            "Run /onboard in a Claude Code session to generate it, or copy\n"
            f"{EXAMPLE_PATH.relative_to(PROJECT_ROOT)} to data/search_config.json and fill it in."
        )
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def autonomy_level() -> str:
    """Return the configured autonomy level: search, tailor, or full."""
    level = load_search_config().get("autonomy", {}).get("level", "search")
    if level not in ("search", "tailor", "full"):
        raise ConfigError(
            f"Invalid autonomy.level {level!r} in data/search_config.json "
            "(expected search, tailor, or full)."
        )
    return level


def require_autonomy(minimum: str, action: str) -> None:
    """Exit unless the configured autonomy level allows `action`.

    Order: search < tailor < full.
    """
    order = ["search", "tailor", "full"]
    current = autonomy_level()
    if order.index(current) < order.index(minimum):
        raise ConfigError(
            f"Refusing to {action}: autonomy level is '{current}' but this step needs "
            f"'{minimum}'. Raise autonomy.level in data/search_config.json if you want "
            "the pipeline to do this automatically."
        )
