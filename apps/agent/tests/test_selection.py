import pytest

import src.model as model_module
import src.visualization_router as router
from src.selection import Selection, current_selection, parse_selection


def test_parse_selection_accepts_only_allowlisted_values():
    ok = parse_selection([(b"x-ai-model", b"gpt-6.1-sol"), (b"x-decision-model", b"Jev")])
    assert ok == Selection("gpt-6.1-sol", "Jev")
    bad = parse_selection([(b"x-ai-model", b"gpt-evil"), (b"x-decision-model", b"decision-1")])
    assert bad == Selection(None, None)
    dup = parse_selection([(b"x-ai-model", b"gpt-6-luna"), (b"x-ai-model", b"claude-sonnet-5.5")])
    assert dup.ai_model is None
    assert parse_selection([(b"x-ai-model", b"\xff")]).ai_model is None


@pytest.fixture
def select():
    tokens = []
    def apply(ai=None, decision=None):
        tokens.append(current_selection.set(Selection(ai, decision)))
    yield apply
    for token in reversed(tokens):
        current_selection.reset(token)


def test_claude_selection_falls_back_without_anthropic_key(monkeypatch, select):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    select(ai="claude-sonnet-5.5")
    fallback = object()
    assert model_module.selected_model(fallback) is fallback


def test_gpt_selection_builds_selected_model(monkeypatch, select):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    model_module._selected_models.clear()
    built = []
    monkeypatch.setattr(model_module, "build_model", lambda **kw: built.append(kw["model_name"]) or "m")
    select(ai="gpt-6.1-sol")
    assert model_module.selected_model(object()) == "m"
    assert built == ["gpt-6.1-sol"]
    model_module._selected_models.clear()


def test_jev_selection_uses_typesafe_route_only_with_key(monkeypatch, select):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")
    select(decision="Jev")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert router.get_router_url() != router.LEGACY_JEV_URL
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert router.get_router_url() == router.LEGACY_JEV_URL
    assert router.request_options([])["json"]["model"] == "jev-latest"
