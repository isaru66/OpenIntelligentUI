"""Model defaults and provider-specific validation."""

import os

import pytest

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI

import src.model as model_module
from src.credentials import Credentials, current_credentials
from src.model import DEFAULT_MODEL, build_model, request_model


def test_default_model_is_gpt_6_luna_on_azure_foundry(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENABLED", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENDPOINT", raising=False)

    fake_provider = lambda: "entra-token"
    monkeypatch.setattr(model_module, "get_azure_token_provider", lambda: fake_provider)

    assert DEFAULT_MODEL == "gpt-6-luna"
    model = build_model()
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-6-luna"
    assert model.openai_api_base == "https://ai-isarar-2855.services.ai.azure.com/openai/v1"
    assert model.reasoning == {"effort": "none"}
    assert model.use_responses_api is True
    assert callable(model.openai_api_key)
    assert model.openai_api_key() == "entra-token"


def test_gpt_6_1_sol_uses_same_foundry_resource_as_default(monkeypatch):
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENABLED", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENDPOINT", raising=False)
    monkeypatch.setattr(model_module, "get_azure_token_provider", lambda: (lambda: "entra-token"))

    default = build_model(model_name="gpt-6-luna")
    sol = build_model(model_name="gpt-6.1-sol")
    assert sol.model_name == "gpt-6.1-sol"
    assert sol.openai_api_base == default.openai_api_base
    assert sol.openai_api_key() == "entra-token"
    assert sol.reasoning == {"effort": "low"}
    assert sol.use_responses_api is True
    assert default.reasoning == {"effort": "none"}


def test_foundry_disabled_or_byok_uses_standard_openai_and_anthropic(monkeypatch):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "server-openai-key")
    monkeypatch.setenv("LLM_MODEL", "chat-latest")

    fallback = build_model()
    assert isinstance(fallback, ChatOpenAI)
    assert fallback.model_name == "chat-latest"
    assert fallback.openai_api_base is None

    token = current_credentials.set(Credentials("byok-openai", "byok-jev"))
    try:
        byok_model = request_model(fallback)
        assert isinstance(byok_model, ChatOpenAI)
        assert byok_model.model_name == "chat-latest"
        assert byok_model.openai_api_base == "https://api.openai.com/v1"
        assert byok_model.openai_api_key.get_secret_value() == "byok-openai"
    finally:
        current_credentials.reset(token)


def test_llm_model_env_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_MODEL", "claude-opus-4-6")
    model = build_model()
    assert model.model == "claude-opus-4-6"


def test_gpt_model_names_route_to_openai_fallback(monkeypatch: pytest.MonkeyPatch):
    # Production fallback: flipping LLM_MODEL to a gpt-* name in the Render
    # dashboard must work without a code change.
    monkeypatch.setenv("LLM_MODEL", "gpt-5.4-2026-03-05")
    model = build_model()
    assert isinstance(model, ChatOpenAI)
    assert model.model_name == "gpt-5.4-2026-03-05"


def test_claude_model_names_route_to_anthropic(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_MODEL", "claude-opus-4-6")
    assert isinstance(build_model(), ChatAnthropic)


def test_max_tokens_fits_full_widget_generation(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "claude-fable-5")
    # langchain-anthropic's default (4096) truncates generateSandboxedUi args
    # mid-stream: css+html arrive but jsFunctions/jsExpressions are cut off, so
    # htmlComplete never fires and the widget never leaves the preview sandbox.
    model = build_model()
    assert model.max_tokens >= 32000


def test_main_uses_build_model():
    import ast
    from pathlib import Path

    main_src = Path(__file__).parent.parent / "main.py"
    tree = ast.parse(main_src.read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert "build_model" in names
    assert "ChatOpenAI" not in main_src.read_text()


@pytest.mark.parametrize("name", ["", "   ", "gemini-example", "typo-model"])
def test_invalid_model_configuration_fails_before_client_creation(monkeypatch, name):
    monkeypatch.setenv("LLM_MODEL", name)
    with pytest.raises(ValueError, match="LLM_MODEL"):
        build_model()


@pytest.mark.parametrize(
    ("model", "key"),
    [
        ("claude-opus-4-6", "ANTHROPIC_API_KEY"),
        ("gpt-5.4-2026-03-05", "OPENAI_API_KEY"),
        ("chat-latest", "OPENAI_API_KEY"),
    ],
)
@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_provider_key_has_actionable_error(monkeypatch, model, key, value):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "false")
    monkeypatch.setenv("LLM_MODEL", model)
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=key):
        build_model()


def test_astream_retries_foundry_sse_rate_limit_api_error_up_to_3_times(monkeypatch):
    import asyncio
    import httpx
    import openai
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import AIMessageChunk, HumanMessage
    from langchain_core.outputs import ChatGenerationChunk, ChatResult

    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr(model_module.asyncio, "sleep", fake_sleep)

    attempts = 0
    rate_limit_error = openai.APIError(
        "Your requests to gpt-6-luna for gpt-6-luna in swedencentral have exceeded token rate limit.",
        request=httpx.Request("POST", "https://ai-isarar-2855.services.ai.azure.com/openai/v1/responses"),
        body=None,
    )

    class StreamingRateLimitedModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "fake-streaming"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[])

        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            nonlocal attempts
            attempts += 1
            # Simulate Responses API initial `response.created` metadata chunk before SSE error
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=[],
                    tool_call_chunks=[],
                    id=f"resp_{attempts}",
                    response_metadata={"id": f"resp_{attempts}", "model_provider": "openai"},
                )
            )
            if attempts <= 3:
                raise rate_limit_error
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=[{"type": "text", "text": "Recovered response", "index": 0}],
                    id=f"resp_{attempts}",
                )
            )

    scoped = model_module.CredentialScopedModel(fallback=StreamingRateLimitedModel())
    monkeypatch.setattr(model_module, "request_model", lambda fallback: fallback)

    async def run():
        return [chunk async for chunk in scoped._astream([HumanMessage(content="hi")])]

    chunks = asyncio.run(run())
    assert attempts == 4
    assert sleeps == [2.0, 4.0, 8.0]
    # Failed attempts' metadata chunks must not leak into the final stream
    assert [c.message.id for c in chunks] == ["resp_4", "resp_4"]
    assert chunks[-1].message.content == [{"type": "text", "text": "Recovered response", "index": 0}]


def test_astream_stops_after_max_3_retries_and_raises(monkeypatch):
    import asyncio
    import httpx
    import openai
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import HumanMessage
    from langchain_core.outputs import ChatResult

    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr(model_module.asyncio, "sleep", fake_sleep)

    attempts = 0
    rate_limit_error = openai.APIError(
        "Your requests to gpt-6-luna for gpt-6-luna in swedencentral have exceeded token rate limit.",
        request=httpx.Request("POST", "https://ai-isarar-2855.services.ai.azure.com/openai/v1/responses"),
        body=None,
    )

    class AlwaysRateLimitedModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "always-failing"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            return ChatResult(generations=[])

        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            nonlocal attempts
            attempts += 1
            if False:
                yield
            raise rate_limit_error

    scoped = model_module.CredentialScopedModel(fallback=AlwaysRateLimitedModel())
    monkeypatch.setattr(model_module, "request_model", lambda fallback: fallback)

    async def run():
        async for _ in scoped._astream([HumanMessage(content="hi")]):
            pass

    with pytest.raises(openai.APIError, match="exceeded token rate limit"):
        asyncio.run(run())
    assert attempts == 4
    assert sleeps == [2.0, 4.0, 8.0]


def test_non_retryable_bad_request_does_not_retry(monkeypatch):
    import httpx
    import openai
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import HumanMessage

    sleeps: list[float] = []
    monkeypatch.setattr(model_module.time, "sleep", lambda d: sleeps.append(d))

    attempts = 0
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "https://api.openai.com/v1/responses"),
    )
    bad_request = openai.BadRequestError(
        "Invalid parameter",
        response=response,
        body={"error": {"message": "Invalid parameter"}},
    )

    class BadRequestModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "bad-request"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            nonlocal attempts
            attempts += 1
            raise bad_request

    scoped = model_module.CredentialScopedModel(fallback=BadRequestModel())
    monkeypatch.setattr(model_module, "request_model", lambda fallback: fallback)

    with pytest.raises(openai.BadRequestError):
        scoped.invoke([HumanMessage(content="hi")])
    assert attempts == 1
    assert sleeps == []


def test_request_model_middleware_shares_3_retry_budget_with_credential_scoped_model(monkeypatch):
    import asyncio
    import httpx
    import openai
    from langchain.agents.middleware import ModelRequest
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.messages import HumanMessage

    sleeps: list[float] = []

    async def fake_sleep(delay: float):
        sleeps.append(delay)

    monkeypatch.setattr(model_module.asyncio, "sleep", fake_sleep)

    attempts = 0
    rate_limit_error = openai.APIError(
        "Your requests to gpt-6-luna for gpt-6-luna in swedencentral have exceeded token rate limit.",
        request=httpx.Request("POST", "https://ai-isarar-2855.services.ai.azure.com/openai/v1/responses"),
        body=None,
    )

    class FailingModel(BaseChatModel):
        @property
        def _llm_type(self):
            return "failing"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            raise rate_limit_error

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            nonlocal attempts
            attempts += 1
            raise rate_limit_error

    base = FailingModel()
    scoped = model_module.CredentialScopedModel(fallback=base)
    monkeypatch.setattr(model_module, "request_model", lambda fallback: base)
    middleware = model_module.RequestModelMiddleware()
    req = ModelRequest(
        model=scoped,
        messages=[HumanMessage(content="hi")],
        tools=[],
        system_message=None,
        state={},
    )

    async def handler(overridden_req):
        return await overridden_req.model.ainvoke(overridden_req.messages)

    with pytest.raises(openai.APIError, match="exceeded token rate limit"):
        asyncio.run(middleware.awrap_model_call(req, handler))
    assert attempts == 4
    assert sleeps == [2.0, 4.0, 8.0]

