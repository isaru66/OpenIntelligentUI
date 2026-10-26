import pytest

import src.model as model_module
import src.visualization_router as router
from src.selection import REASONING_EFFORTS, Selection, current_selection, parse_selection


def test_parse_selection_accepts_only_allowlisted_values():
    ok = parse_selection([(b"x-ai-model", b"gpt-6.1-sol"), (b"x-decision-model", b"Jev")])
    assert ok == Selection("gpt-6.1-sol", "Jev", "medium")
    bad = parse_selection([(b"x-ai-model", b"gpt-evil"), (b"x-decision-model", b"decision-1")])
    assert bad == Selection(None, None)
    dup = parse_selection([(b"x-ai-model", b"gpt-6-luna"), (b"x-ai-model", b"claude-sonnet-5.5")])
    assert dup.ai_model is None
    assert parse_selection([(b"x-ai-model", b"\xff")]).ai_model is None


@pytest.fixture
def select():
    tokens = []
    def apply(ai=None, decision=None, effort=None):
        tokens.append(current_selection.set(Selection(ai, decision, effort)))
    yield apply
    for token in reversed(tokens):
        current_selection.reset(token)


@pytest.fixture(autouse=True)
def clear_selected_cache():
    model_module._selected_models.clear()
    yield
    model_module._selected_models.clear()


def test_claude_selection_errors_without_anthropic_key(monkeypatch, select):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    select(ai="claude-sonnet-5.5")
    fallback = object()
    with pytest.raises(model_module.ModelSelectionError, match="administrator"):
        model_module.selected_model(fallback)


def test_gpt_selection_builds_selected_model(monkeypatch, select):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    model_module._selected_models.clear()
    built = []
    monkeypatch.setattr(model_module, "build_model", lambda **kw: built.append(kw) or "m")
    select(ai="gpt-6.1-sol")
    assert model_module.selected_model(object()) == "m"
    assert built == [{"model_name": "gpt-6.1-sol", "reasoning_effort": "medium"}]
    model_module._selected_models.clear()


def test_deepseek_selection_retains_public_alias_and_caches_each_effort(monkeypatch, select):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")
    monkeypatch.setattr(model_module, "get_azure_token_provider", lambda: (lambda: "entra-token"))
    selected = {}
    for effort in ("low", "medium", "high"):
        select(ai="deepseek-v4.1-flash", effort=effort)
        selected[effort] = model_module.selected_model(object())
        assert selected[effort].model_name == "FW-DeepSeek-V4.1-Flash"
        assert selected[effort].reasoning_effort == effort
        assert current_selection.get().ai_model == "deepseek-v4.1-flash"
    select(ai="deepseek-v4.1-flash", effort="medium")
    assert model_module.selected_model(object()) is selected["medium"]
    assert len({id(model) for model in selected.values()}) == 3


def test_deepseek_selection_errors_when_foundry_is_disabled(monkeypatch, select):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "public-key")
    select(ai="deepseek-v4.1-flash")
    with pytest.raises(model_module.ModelSelectionError, match="administrator"):
        model_module.selected_model(object())
    assert not model_module._selected_models


@pytest.mark.parametrize("effort", ["none", "xhigh", "max"])
def test_deepseek_unsupported_selected_effort_normalizes_to_medium(effort):
    assert parse_selection([
        (b"x-ai-model", b"deepseek-v4.1-flash"),
        (b"x-reasoning-effort", effort.encode()),
    ]) == Selection("deepseek-v4.1-flash", reasoning_effort="medium")


def test_jev_selection_uses_typesafe_route_only_with_key(monkeypatch, select):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")
    select(decision="Jev")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    assert router.get_router_url() != router.LEGACY_JEV_URL
    monkeypatch.setenv("TYPESAFE_API_KEY", "k")
    assert router.get_router_url() == router.LEGACY_JEV_URL
    assert router.request_options([])["json"]["model"] == "jev-latest"


@pytest.mark.parametrize("model", REASONING_EFFORTS)
def test_all_model_efforts_are_allowlisted(model):
    for effort in REASONING_EFFORTS[model]:
        selected = parse_selection([
            (b"x-ai-model", model.encode()),
            (b"x-reasoning-effort", effort.encode()),
        ])
        assert selected == Selection(model, reasoning_effort=effort)


@pytest.mark.parametrize("model", REASONING_EFFORTS)
@pytest.mark.parametrize("values", [
    [], [b""], [b"HIGH"], [b"unknown"], [b"\xff"], [b"\thigh"],
    [b"high\n"], [b"high,low"], [b"high", b"low"], [b"high", b"high"],
])
def test_missing_malformed_or_duplicate_effort_defaults_to_medium(model, values):
    selection = parse_selection(
        [(b"x-ai-model", model.encode())]
        + [(b"x-reasoning-effort", value) for value in values]
    )
    assert selection == Selection(model, reasoning_effort="medium")


@pytest.mark.parametrize("model", ["gpt-6.1-sol", "claude-sonnet-5.5"])
def test_none_is_not_supported_except_on_luna(model):
    assert parse_selection([
        (b"x-ai-model", model.encode()), (b"x-reasoning-effort", b"none"),
    ]).reasoning_effort == "medium"


@pytest.mark.parametrize("models", [[], [b"unknown"], [b"\xff"], [b"gpt-6-luna\n"],
                                     [b"gpt-6-luna", b"gpt-6-luna"]])
def test_effort_without_valid_model_preserves_fallback(models, select):
    selection = parse_selection(
        [(b"x-ai-model", value) for value in models] + [(b"x-reasoning-effort", b"max")]
    )
    assert selection == Selection()
    select(ai=selection.ai_model, effort=selection.reasoning_effort)
    fallback = object()
    assert model_module.selected_model(fallback) is fallback


def test_cache_separates_efforts_and_default_model_does_not_bypass_selection(monkeypatch, select):
    monkeypatch.setenv("LLM_MODEL", "gpt-6-luna")
    built = []
    def build(**kwargs):
        result = object()
        built.append((kwargs, result))
        return result
    monkeypatch.setattr(model_module, "build_model", build)
    fallback = object()
    select(ai="gpt-6-luna", effort="medium")
    medium = model_module.selected_model(fallback)
    select(ai="gpt-6-luna", effort="max")
    maximum = model_module.selected_model(fallback)
    select(ai="gpt-6-luna", effort="medium")
    assert model_module.selected_model(fallback) is medium
    assert medium is not maximum and medium is not fallback and maximum is not fallback
    assert [kwargs["reasoning_effort"] for kwargs, _ in built] == ["medium", "max"]


def test_explicit_selection_configuration_errors_are_fixed_and_not_cached(monkeypatch, select):
    def fail(**kwargs):
        raise RuntimeError("private provider configuration")
    monkeypatch.setattr(model_module, "build_model", fail)
    select(ai="gpt-6-luna", effort="max")
    with pytest.raises(model_module.ModelSelectionError) as error:
        model_module.selected_model(object())
    assert "private" not in str(error.value)
    assert not model_module._selected_models
