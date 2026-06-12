"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import json
import os

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

# Groq model used by the two LLM-backed tools (suggest_outfit, create_fit_card).
_MODEL = "llama-3.3-70b-versatile"


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()
    keywords = set(description.lower().split())

    scored = []
    for item in listings:
        # 1. Price filter (skip if no ceiling given)
        if max_price is not None and item["price"] > max_price:
            continue

        # 2. Size filter — token-based, case-insensitive.
        #    "S/M" -> {"S", "M"}; "One Size" items fit any requested size.
        if size is not None:
            item_size = item["size"].upper()
            size_tokens = {tok.strip() for tok in item_size.split("/")}
            if size.upper() not in size_tokens and "ONE SIZE" not in item_size:
                continue

        # 3. Relevance score — how many keywords appear across title,
        #    description, and style_tags (combined, lowercased).
        haystack = (
            item["title"]
            + " "
            + item["description"]
            + " "
            + " ".join(item["style_tags"])
        ).lower()
        score = sum(1 for kw in keywords if kw in haystack)

        # 4. Drop non-matches.
        if score > 0:
            scored.append((score, item))

    # Sort by score, highest first (stable: ties keep dataset order).
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(
    new_item: dict,
    wardrobe: dict,
    style_profile: dict | None = None,
    trends: list | None = None,
) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.
        style_profile: (optional, stretch) remembered user style preferences,
                  e.g. {"preferred_styles": ["y2k", "streetwear"]}. When present,
                  the outfit is biased toward these styles WITHOUT the user having
                  to re-state them.
        trends:   (optional, stretch) list of currently-trending style tags. When
                  present, the suggestion leans into any that fit the item.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item['title']} — category: {new_item['category']}, "
        f"colors: {', '.join(new_item['colors'])}, "
        f"style: {', '.join(new_item['style_tags'])}, "
        f"condition: {new_item['condition']}"
    )

    # Optional stretch context: remembered preferences + current trends.
    context = ""
    if style_profile and style_profile.get("preferred_styles"):
        context += (
            "\nThe user generally likes these styles (from their saved profile): "
            f"{', '.join(style_profile['preferred_styles'])}. Lean toward these "
            "where it makes sense.\n"
        )
    if trends:
        context += (
            f"\nCurrently trending styles: {', '.join(trends)}. If any of these "
            "fit the item, work them in and mention they're trending.\n"
        )

    items = wardrobe.get("items", [])

    if not items:
        # Branch 1: empty wardrobe → general styling advice (failure mode).
        prompt = (
            f"A thrifter is considering buying this secondhand item:\n{item_desc}\n"
            f"{context}\n"
            "They haven't told us anything about their existing wardrobe. Give "
            "general styling advice for this piece: what kinds of items pair well "
            "with it, what vibe/aesthetic it suits, and how to wear it. "
            "Keep it to 2-4 concrete sentences."
        )
    else:
        # Branch 2: real wardrobe → outfits naming specific owned pieces.
        wardrobe_lines = "\n".join(
            f"- {it['name']}" + (f" ({it['notes']})" if it.get("notes") else "")
            for it in items
        )
        prompt = (
            f"A thrifter is considering buying this secondhand item:\n{item_desc}\n"
            f"{context}\n"
            f"Here is their existing wardrobe:\n{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfits that combine the new item with SPECIFIC "
            "pieces from their wardrobe. Reference the wardrobe pieces by name. "
            "Be concrete and concise (2-4 sentences total)."
        )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are a sharp, practical thrift stylist. "
                    "You give specific, wearable outfit ideas — no fluff.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        # LLM/API failure → plain fallback so the agent stays useful.
        return (
            f"Couldn't reach the styling model ({exc.__class__.__name__}). "
            f"As a quick tip, treat the {new_item['title'].lower()} as your "
            "statement piece and build around it with simple, neutral basics."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # 1. Guard against an empty / whitespace-only outfit (failure mode).
    if not outfit or not outfit.strip():
        return "Couldn't write a fit card — no outfit was provided to caption."

    title = new_item.get("title", "this piece")
    price = new_item.get("price")
    platform = new_item.get("platform", "online")
    price_str = f"${price:.0f}" if isinstance(price, (int, float)) else "a steal"

    prompt = (
        f"Write a short, shareable caption (2-4 sentences) for a thrifted outfit.\n"
        f"Item: {title}, bought for {price_str} on {platform}.\n"
        f"Outfit: {outfit}\n\n"
        "Make it sound like a real, casual OOTD social post — NOT a product "
        f"description. Mention the item name, the price ({price_str}), and the "
        f"platform ({platform}) naturally, once each. Capture the vibe in "
        "specific terms. Emojis are welcome but don't overdo it."
    )

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You write punchy, authentic thrift-haul captions "
                    "the way a real person posts them — casual, specific, a little "
                    "hyped. Never sound like a catalog.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.9,  # higher temp → varied wording each run
        )
        return response.choices[0].message.content.strip()
    except Exception as exc:
        # LLM/API failure → plain fallback caption rather than crashing.
        return (
            f"just thrifted this {title.lower()} for {price_str} on {platform} "
            f"and i'm obsessed 😍 (caption generator hit a snag: "
            f"{exc.__class__.__name__})"
        )


# ── Tool 4 (stretch): compare_price ───────────────────────────────────────────

def compare_price(item: dict, listings: list | None = None) -> dict:
    """
    Assess whether an item's price is fair, compared to similar listings in the
    dataset (same category). Pure logic — no LLM call.

    Args:
        item:     The listing dict to evaluate.
        listings: The pool to compare against. Defaults to the full dataset.

    Returns:
        A dict:
            {
              "verdict": "great deal" | "fair" | "pricey" | "unknown",
              "item_price": float,
              "median_comparable": float | None,
              "num_comparables": int,
              "reasoning": str,   # human-readable explanation citing comparables
            }
        "unknown" (with reasoning) when there are too few comparables to judge.
    """
    if listings is None:
        listings = load_listings()

    price = item["price"]
    category = item.get("category")

    # Comparables = same category, excluding the item itself.
    comps = [
        x["price"]
        for x in listings
        if x.get("category") == category and x.get("id") != item.get("id")
    ]

    if len(comps) < 2:
        return {
            "verdict": "unknown",
            "item_price": price,
            "median_comparable": None,
            "num_comparables": len(comps),
            "reasoning": (
                f"Not enough comparable {category} listings to judge this "
                f"${price:.0f} price fairly."
            ),
        }

    comps.sort()
    n = len(comps)
    median = comps[n // 2] if n % 2 else (comps[n // 2 - 1] + comps[n // 2]) / 2

    if price <= 0.85 * median:
        verdict, phrase = "great deal", "a great deal"
    elif price <= 1.15 * median:
        verdict, phrase = "fair", "fairly priced"
    else:
        verdict, phrase = "pricey", "on the pricey side"

    reasoning = (
        f"Compared to {n} other {category} listings (median ${median:.0f}, "
        f"range ${comps[0]:.0f}–${comps[-1]:.0f}), this ${price:.0f} is "
        f"{phrase}."
    )
    return {
        "verdict": verdict,
        "item_price": price,
        "median_comparable": median,
        "num_comparables": n,
        "reasoning": reasoning,
    }


# ── Tool 5 (stretch): get_trends ──────────────────────────────────────────────

def get_trends(size: str | None = None) -> list:
    """
    Return currently-trending style tags from the local mock trends dataset
    (data/trends.json). Stands in for "recent posts/tags on a fashion platform".

    Args:
        size: optional size to filter trends by size range; trends tagged for a
              specific size only surface when that size is requested, while
              "all"-size trends always surface.

    Returns:
        A list of trending style tag strings (possibly empty if the file is
        missing or unreadable — never raises).
    """
    path = os.path.join(os.path.dirname(__file__), "data", "trends.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []  # missing/corrupt trends file → no trends, agent still works

    out = []
    for entry in data.get("trending", []):
        entry_size = entry.get("size", "all")
        if entry_size == "all" or size is None or entry_size.upper() == size.upper():
            out.append(entry["tag"])
    return out
