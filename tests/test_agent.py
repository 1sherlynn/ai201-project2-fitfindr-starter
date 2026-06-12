"""
tests/test_agent.py

Tests for the planning loop (agent.py) and the style-memory module. The
LLM-backed and disk-writing calls are stubbed so these run offline and don't
touch the real `style_profile.json`.
"""

import agent
import style_memory
from utils.data_loader import get_example_wardrobe


def _stub_llm_and_io(monkeypatch):
    """Replace the LLM tools + profile I/O that run_agent calls, so the planning
    loop is tested in isolation (no network, no file writes)."""
    monkeypatch.setattr(agent, "suggest_outfit", lambda *a, **k: "stub outfit")
    monkeypatch.setattr(agent, "create_fit_card", lambda *a, **k: "stub card")
    monkeypatch.setattr(agent, "load_style_profile", lambda *a, **k: {"preferred_styles": []})
    monkeypatch.setattr(agent, "update_profile_with_item", lambda *a, **k: {})
    monkeypatch.setattr(agent, "get_trends", lambda *a, **k: [])


def test_run_agent_happy_path_runs_all_steps(monkeypatch):
    _stub_llm_and_io(monkeypatch)
    session = agent.run_agent("vintage graphic tee under $30", get_example_wardrobe())
    assert session["error"] is None
    assert session["selected_item"] is not None
    assert session["fit_card"] == "stub card"
    # state hand-off: the selected item is the top search result.
    assert session["selected_item"] is session["search_results"][0]


def test_run_agent_no_results_early_return(monkeypatch):
    # ADAPTIVENESS: impossible query → error set, later tools never run.
    _stub_llm_and_io(monkeypatch)
    session = agent.run_agent("designer ballgown size XXS under $5", get_example_wardrobe())
    assert session["error"] is not None
    assert session["fit_card"] is None
    assert session["outfit_suggestion"] is None


def test_run_agent_retry_fallback_drops_size(monkeypatch):
    # STRETCH +1: size XS has no jeans → retry without size finds them.
    _stub_llm_and_io(monkeypatch)
    session = agent.run_agent("levis jeans size XS", get_example_wardrobe())
    assert session["error"] is None
    assert session["retry_note"] is not None
    assert "size" in session["retry_note"].lower()
    assert session["selected_item"] is not None


def test_run_agent_attaches_price_assessment(monkeypatch):
    # STRETCH +2: a price assessment dict is attached on the happy path.
    _stub_llm_and_io(monkeypatch)
    session = agent.run_agent("vintage graphic tee under $30", get_example_wardrobe())
    assert session["price_assessment"] is not None
    assert "verdict" in session["price_assessment"]


# ── style memory module ───────────────────────────────────────────────────────

def test_style_memory_accumulates_and_dedupes(tmp_path):
    p = str(tmp_path / "sp.json")
    assert style_memory.load_style_profile(p) == {"preferred_styles": []}
    style_memory.update_profile_with_item({"style_tags": ["y2k", "vintage"]}, p)
    style_memory.update_profile_with_item({"style_tags": ["y2k", "streetwear"]}, p)
    prefs = style_memory.load_style_profile(p)["preferred_styles"]
    assert prefs == ["y2k", "vintage", "streetwear"]  # deduped, order preserved


def test_style_memory_survives_reload(tmp_path):
    # The whole point: a later "session" reads what an earlier one saved.
    p = str(tmp_path / "sp.json")
    style_memory.update_profile_with_item({"style_tags": ["grunge"]}, p)
    assert "grunge" in style_memory.load_style_profile(p)["preferred_styles"]
