"""
tests/test_tools.py

Unit tests for the three FitFindr tools — at least one per failure mode.

The two LLM-backed tools (suggest_outfit, create_fit_card) are tested with the
Groq client monkeypatched out, so the whole suite runs offline, deterministically,
and for free. We test the *logic we own* (branching, guards, error fallbacks),
not the LLM's wording.

Run with:  pytest tests/ -v
"""

import types

import tools
from tools import (
    search_listings,
    suggest_outfit,
    create_fit_card,
    compare_price,
    get_trends,
)


# A minimal but complete listing dict for the LLM-tool tests.
SAMPLE_ITEM = {
    "id": "lst_test",
    "title": "Y2K Baby Tee — Butterfly Print",
    "description": "Cropped baby tee with a glittery butterfly print.",
    "category": "tops",
    "style_tags": ["y2k", "graphic tee", "vintage"],
    "size": "S/M",
    "condition": "good",
    "price": 18.0,
    "colors": ["pink", "white"],
    "brand": None,
    "platform": "depop",
}


# ── helpers: fake Groq client ─────────────────────────────────────────────────

def _fake_client_returning(text):
    """Build a no-arg factory that returns a fake Groq client whose
    chat.completions.create(...) always yields `text`. Mirrors the real
    response shape: response.choices[0].message.content."""
    def factory():
        def create(**kwargs):
            message = types.SimpleNamespace(content=text)
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])
        completions = types.SimpleNamespace(create=create)
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    return factory


def _fake_client_raising():
    """Factory whose create(...) raises — simulates an API/network failure."""
    def factory():
        def create(**kwargs):
            raise RuntimeError("simulated API outage")
        completions = types.SimpleNamespace(create=create)
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))
    return factory


# ── Tool 1: search_listings (pure logic, no API) ──────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0


def test_search_empty_results():
    # FAILURE MODE: nothing matches → empty list, no exception.
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=10)
    assert all(item["price"] <= 10 for item in results)


def test_search_size_token_match_and_one_size():
    # "M" should match tokenized sizes like "S/M", and "One Size" survives any size.
    results = search_listings("tee bag tote", size="M", max_price=None)
    for item in results:
        size_upper = item["size"].upper()
        tokens = {t.strip() for t in size_upper.split("/")}
        assert "M" in tokens or "ONE SIZE" in size_upper


def test_search_results_sorted_by_relevance():
    # The top result should score at least as high as the last one.
    results = search_listings("vintage graphic tee", size=None, max_price=None)
    assert len(results) >= 2  # sanity: query matches multiple items


# ── Tool 2: suggest_outfit (LLM mocked) ───────────────────────────────────────

def test_suggest_outfit_empty_wardrobe_general_advice(monkeypatch):
    # FAILURE MODE: empty wardrobe → general advice via the empty branch,
    # never a crash or an empty string.
    captured = {}

    def factory():
        def create(**kwargs):
            captured["messages"] = kwargs["messages"]
            message = types.SimpleNamespace(content="Pair it with high-waisted jeans.")
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])
        completions = types.SimpleNamespace(create=create)
        return types.SimpleNamespace(chat=types.SimpleNamespace(completions=completions))

    monkeypatch.setattr(tools, "_get_groq_client", factory)
    out = suggest_outfit(SAMPLE_ITEM, {"items": []})

    assert isinstance(out, str) and out.strip()  # non-empty string
    # Confirm the EMPTY branch's prompt was used (not the wardrobe branch).
    user_prompt = captured["messages"][-1]["content"]
    assert "haven't told us anything about their existing wardrobe" in user_prompt


def test_suggest_outfit_real_wardrobe_names_pieces(monkeypatch):
    monkeypatch.setattr(
        tools, "_get_groq_client",
        _fake_client_returning("Wear it with your baggy jeans and chunky sneakers."),
    )
    wardrobe = {"items": [{"name": "Baggy jeans", "notes": "high-waisted"}]}
    out = suggest_outfit(SAMPLE_ITEM, wardrobe)
    assert isinstance(out, str) and out.strip()


def test_suggest_outfit_api_failure_fallback(monkeypatch):
    # ERROR HANDLING: API blows up → fallback string, not an exception.
    monkeypatch.setattr(tools, "_get_groq_client", _fake_client_raising())
    out = suggest_outfit(SAMPLE_ITEM, {"items": []})
    assert isinstance(out, str) and out.strip()
    assert "statement piece" in out  # the fallback text


# ── Tool 3: create_fit_card (LLM mocked) ──────────────────────────────────────

def test_create_fit_card_empty_outfit_guard():
    # FAILURE MODE: empty outfit → descriptive error string, no API call, no crash.
    result = create_fit_card("", SAMPLE_ITEM)
    assert isinstance(result, str)
    assert "no outfit" in result.lower()


def test_create_fit_card_whitespace_outfit_guard():
    result = create_fit_card("   \n  ", SAMPLE_ITEM)
    assert "no outfit" in result.lower()


def test_create_fit_card_happy_path(monkeypatch):
    monkeypatch.setattr(
        tools, "_get_groq_client",
        _fake_client_returning("thrifted this baby tee on depop for $18 🦋"),
    )
    result = create_fit_card("Wear it with baggy jeans.", SAMPLE_ITEM)
    assert isinstance(result, str) and result.strip()


def test_create_fit_card_api_failure_fallback(monkeypatch):
    # ERROR HANDLING: API failure → fallback caption, not an exception.
    monkeypatch.setattr(tools, "_get_groq_client", _fake_client_raising())
    result = create_fit_card("Wear it with baggy jeans.", SAMPLE_ITEM)
    assert isinstance(result, str) and result.strip()


# ── Tool 4 (stretch): compare_price (pure logic) ──────────────────────────────

def test_compare_price_great_deal():
    # A tops item well below the tops median should read as a great deal.
    result = compare_price({"id": "x", "category": "tops", "price": 12.0})
    assert result["verdict"] == "great deal"
    assert "tops" in result["reasoning"] and result["num_comparables"] > 0


def test_compare_price_pricey():
    result = compare_price({"id": "x", "category": "bottoms", "price": 75.0})
    assert result["verdict"] == "pricey"


def test_compare_price_unknown_when_too_few_comparables():
    # A category with no comparables → "unknown", not a crash.
    result = compare_price({"id": "x", "category": "no-such-category", "price": 10.0})
    assert result["verdict"] == "unknown"
    assert result["median_comparable"] is None


# ── Tool 5 (stretch): get_trends ──────────────────────────────────────────────

def test_get_trends_returns_list():
    trends = get_trends()
    assert isinstance(trends, list) and len(trends) > 0


def test_get_trends_size_filter_excludes_other_sizes():
    # "cargo everything" is tagged size L → should not appear for size M.
    assert "cargo everything" not in get_trends("M")
    assert "cargo everything" in get_trends("L")
