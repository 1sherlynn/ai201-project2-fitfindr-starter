"""
style_memory.py — style profile memory (stretch feature).

Persists a user's style preferences to a JSON file so they survive across
sessions. This is the agent's *long-term* memory: unlike the per-run session
dict (which is wiped each interaction), this lives on disk, so a later session
can reuse what an earlier one learned WITHOUT the user re-entering anything.

Storage: a single JSON file, default `style_profile.json` in the repo root.
Shape: {"preferred_styles": ["y2k", "streetwear", ...]}
"""

import json
import os

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "style_profile.json")


def load_style_profile(path: str = _DEFAULT_PATH) -> dict:
    """Load the saved style profile, or a fresh empty one if none exists."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"preferred_styles": []}


def save_style_profile(profile: dict, path: str = _DEFAULT_PATH) -> None:
    """Persist the style profile to disk."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, indent=2)


def update_profile_with_item(item: dict, path: str = _DEFAULT_PATH) -> dict:
    """
    Fold a selected item's style_tags into the saved profile (deduped, capped),
    persist it, and return the updated profile. This is how preferences
    accumulate across sessions from what the user actually picks.
    """
    profile = load_style_profile(path)
    preferred = profile.get("preferred_styles", [])
    for tag in item.get("style_tags", []):
        if tag not in preferred:
            preferred.append(tag)
    profile["preferred_styles"] = preferred[-12:]  # keep the most recent 12
    save_style_profile(profile, path)
    return profile
