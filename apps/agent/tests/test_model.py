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
    assert model.max_tokens == model_module.MAX_TOKENS
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


@pytest.mark.parametrize("name", ["deepseek-v4.1-flash", "FW-DeepSeek-V4.1-Flash"])
@pytest.mark.parametrize("configured_by_env", [False, True])
def test_deepseek_uses_exact_deployment_chat_completions_and_existing_entra_auth(monkeypatch, name, configured_by_env):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENDPOINT", "https://example.services.ai.azure.com")
    monkeypatch.setenv("LLM_USE_RESPONSES_API", "true")
    monkeypatch.delenv("LLM_REASONING_EFFORT", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = lambda: "entra-token"
    monkeypatch.setattr(model_module, "get_azure_token_provider", lambda: provider)
    if configured_by_env:
        monkeypatch.setenv("LLM_MODEL", name)
    model = build_model(**({} if configured_by_env else {"model_name": name}))
    assert model.model_name == "FW-DeepSeek-V4.1-Flash"
    assert model.openai_api_base == "https://example.services.ai.azure.com/openai/v1"
    assert model.openai_api_key is provider
    assert model.use_responses_api is False
    assert model.reasoning is None
    assert model.reasoning_effort == "medium"
    assert model.max_tokens == model_module.MAX_TOKENS
    assert model.max_retries == 0


@pytest.mark.parametrize("name", ["deepseek-v4.1-flash", "FW-DeepSeek-V4.1-Flash"])
@pytest.mark.parametrize("allow_unconfigured", [False, True])
def test_deepseek_cannot_fall_back_to_public_openai(monkeypatch, name, allow_unconfigured):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "public-key")
    with pytest.raises(ValueError, match="AZURE_AI_FOUNDRY_ENABLED=true"):
        build_model(model_name=name, allow_unconfigured=allow_unconfigured)


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_deepseek_headerless_effort_and_explicit_override(monkeypatch, effort):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")
    monkeypatch.setenv("LLM_REASONING_EFFORT", effort)
    monkeypatch.setattr(model_module, "get_azure_token_provider", lambda: (lambda: "entra-token"))
    assert build_model(model_name="deepseek-v4.1-flash").reasoning_effort == effort
    monkeypatch.setenv("LLM_REASONING_EFFORT", "none")
    assert build_model(model_name="deepseek-v4.1-flash", reasoning_effort=effort).reasoning_effort == effort


@pytest.mark.parametrize("effort", ["", "none", "xhigh", "max", "HIGH"])
def test_deepseek_rejects_unsupported_environment_effort(monkeypatch, effort):
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")
    monkeypatch.setenv("LLM_REASONING_EFFORT", effort)
    with pytest.raises(ValueError, match="LLM_REASONING_EFFORT"):
        build_model(model_name="deepseek-v4.1-flash")


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


@pytest.mark.parametrize("foundry", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(("name", "effort"), [
    (name, effort)
    for name, efforts in model_module.REASONING_EFFORTS.items()
    for effort in efforts
])
def test_selected_effort_reaches_serialized_tool_capable_provider_request(monkeypatch, foundry, streaming, name, effort):
    """Capture actual SDK HTTP serialization, without sending anything to a provider."""
    import json
    import httpx

    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", str(foundry).lower())
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "low")
    monkeypatch.setattr(model_module, "get_azure_token_provider", lambda: (lambda: "test-token"))
    captured = []

    def capture(self, request, **kwargs):
        captured.append(request)
        # A 400 response avoids SDK retries and proves the final JSON wire body.
        return httpx.Response(400, json={"error": {"type": "invalid_request_error", "message": "test capture"}}, request=request)

    monkeypatch.setattr(httpx.Client, "send", capture)
    if name == "deepseek-v4.1-flash" and not foundry:
        with pytest.raises(ValueError, match="Azure AI Foundry"):
            build_model(model_name=name, reasoning_effort=effort)
        assert captured == []
        return
    model = build_model(model_name=name, reasoning_effort=effort)
    tools = [{
        "name": "get_weather", "description": "Look up weather.",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
    }]
    with pytest.raises((model_module.openai.BadRequestError, model_module.anthropic.BadRequestError)):
        bound = model.bind_tools(tools)
        if streaming:
            list(bound.stream("Weather in Paris?"))
        else:
            bound.invoke("Weather in Paris?")
    assert len(captured) == 1
    payload = json.loads(captured[0].content)
    assert payload.get("stream", False) is streaming
    assert payload["model"] == ("FW-DeepSeek-V4.1-Flash" if name == "deepseek-v4.1-flash" else name)
    if name == "deepseek-v4.1-flash":
        assert captured[0].url.path.endswith("/chat/completions")
        assert payload["tools"][0]["function"]["name"] == "get_weather"
        assert payload["reasoning_effort"] == effort
        assert payload["max_completion_tokens"] == model_module.MAX_TOKENS
        assert "reasoning" not in payload
        assert "max_output_tokens" not in payload
    elif name.startswith("claude-"):
        assert payload["tools"][0]["name"] == "get_weather"
        assert "reasoning_effort" not in payload
        assert captured[0].url.path.endswith("/messages")
        assert payload["output_config"]["effort"] == effort
        assert payload["thinking"] == {"type": "adaptive"}
        assert payload["max_tokens"] == model_module.MAX_TOKENS
    else:
        assert payload["tools"][0]["name"] == "get_weather"
        assert "reasoning_effort" not in payload
        assert captured[0].url.path.endswith("/responses")
        assert payload["reasoning"] == {"effort": effort}
        assert payload["max_output_tokens"] == model_module.MAX_TOKENS
    assert model.max_retries == 0


@pytest.mark.parametrize(("name", "effort"), [
    ("gpt-6-luna", "auto"), ("gpt-6.1-sol", "none"), ("claude-sonnet-5.5", "none"),
    ("chat-latest", "medium"), ("claude-opus-4-6", "high"), ("gpt-6-luna", "HIGH"),
    ("deepseek-v4.1-flash", "none"), ("deepseek-v4.1-flash", "xhigh"),
    ("deepseek-v4.1-flash", "max"), ("FW-DeepSeek-V4.1-Flash", "none"),
])
def test_explicit_effort_rejects_unsupported_combinations(name, effort):
    with pytest.raises(ValueError, match="combination"):
        build_model(model_name=name, reasoning_effort=effort)


def test_headerless_provider_settings_are_not_changed_by_picker_defaults(monkeypatch):
    monkeypatch.setenv("LLM_REASONING_EFFORT", "high")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")
    monkeypatch.setattr(model_module, "get_azure_token_provider", lambda: (lambda: "test-token"))
    assert build_model(model_name="gpt-6-luna").reasoning == {"effort": "high"}
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    standard = build_model(model_name="gpt-6-luna")
    assert standard.reasoning is None
    assert standard.use_responses_api is None
    claude = build_model(model_name="claude-sonnet-5.5")
    assert claude.effort is None
    assert claude.thinking is None


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
