"""Chat model factory for the agent."""

import os
from contextlib import contextmanager

from langchain.agents.middleware import AgentMiddleware
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.messages import AIMessageChunk
from pydantic import Field
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel

from src.azure_auth import (
    get_azure_token_provider,
    get_foundry_openai_base_url,
    is_azure_foundry_enabled,
)

DEFAULT_MODEL = "gpt-6-luna"
BYOK_DEFAULT_MODEL = "chat-latest"

FOUNDRY_MODEL_PREFIXES = (
    "gpt-",
    "Phi-",
    "DeepSeek-",
    "grok-",
    "Kimi-",
    "Llama-",
)

# langchain-anthropic defaults max_tokens to 4096, which truncates
# generateSandboxedUi tool args mid-stream (jsFunctions/jsExpressions never
# arrive and the widget is stuck in its preview sandbox). Widget generation
# routinely needs tens of thousands of output tokens.
MAX_TOKENS = 64000


def _is_foundry_or_openai_model(model_name: str) -> bool:
    return model_name == "chat-latest" or model_name.startswith(FOUNDRY_MODEL_PREFIXES)


def build_model(*, allow_unconfigured: bool = False) -> BaseChatModel:
    model_name = os.environ.get("LLM_MODEL", DEFAULT_MODEL).strip()
    is_openai = _is_foundry_or_openai_model(model_name)
    is_claude = model_name.startswith("claude-")
    if not is_openai and not is_claude:
        raise ValueError(
            "LLM_MODEL must name a supported provider: claude-* (Anthropic) "
            "or gpt-*/chat-latest/Phi-*/DeepSeek-*/grok-*/Kimi-*/Llama-* (Azure AI Foundry / OpenAI). "
            "Unset LLM_MODEL to use the default."
        )
    if is_claude:
        if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
            if allow_unconfigured:
                return UnconfiguredModel()
            raise ValueError(
                "ANTHROPIC_API_KEY is required for the selected LLM_MODEL provider. "
                "Set it in the agent environment and restart the agent."
            )
        return ChatAnthropic(
            model=model_name,
            max_tokens=MAX_TOKENS,
        )

    from langchain_openai import ChatOpenAI

    if is_azure_foundry_enabled():
        reasoning_effort = os.environ.get("LLM_REASONING_EFFORT", "none").strip()
        use_responses_api = os.environ.get("LLM_USE_RESPONSES_API", "").strip().lower() in {
            "1",
            "true",
            "yes",
        }
        foundry_kwargs: dict = {
            "model": model_name,
            "base_url": get_foundry_openai_base_url(),
            "api_key": get_azure_token_provider(),
        }
        if use_responses_api:
            foundry_kwargs["use_responses_api"] = True
        elif reasoning_effort:
            foundry_kwargs["reasoning_effort"] = reasoning_effort
        return ChatOpenAI(**foundry_kwargs)

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        if allow_unconfigured:
            return UnconfiguredModel()
        raise ValueError(
            "OPENAI_API_KEY is required for the selected LLM_MODEL provider. "
            "Set it in the agent environment and restart the agent."
        )
    return ChatOpenAI(model=model_name)


class UnconfiguredModel(BaseChatModel):
    """Compile a BYOK-only graph without constructing a provider with fake credentials."""

    @property
    def _llm_type(self):
        return "unconfigured"

    def _generate(self, *args, **kwargs):
        raise ValueError("Provider credentials are required. Add OpenAI and Jev keys.")

    def bind_tools(self, tools, **kwargs):
        return self


def request_model(fallback):
    from src.credentials import current_credentials
    credentials = current_credentials.get()
    if credentials is None:
        return fallback
    from langchain_openai import ChatOpenAI
    from openai import AsyncOpenAI, OpenAI, DefaultAsyncHttpxClient, DefaultHttpxClient

    # SDK None defaults inherit server organization/project settings. Explicit
    # clients with empty scopes and isolated transports prevent that inheritance,
    # including server HTTP(S)_PROXY and OPENAI_PROXY settings.
    options = {
        "api_key": credentials.openai,
        "base_url": "https://api.openai.com/v1",
        "organization": "",
        "project": "",
    }
    sync_client = OpenAI(**options, http_client=DefaultHttpxClient(trust_env=False))
    async_client = AsyncOpenAI(
        **options, http_client=DefaultAsyncHttpxClient(trust_env=False)
    )
    # After construction, None omits these headers without rereading env vars.
    for client in (sync_client, async_client):
        client.organization = None
        client.project = None
        client.admin_api_key = None
        client.webhook_secret = None
        # The SDK merges OPENAI_CUSTOM_HEADERS even with default_headers={}.
        # Clear that merge before any request so host Authorization cannot win.
        client._custom_headers = {}
    model = ChatOpenAI(
        model=BYOK_DEFAULT_MODEL,
        api_key=credentials.openai,
        base_url=options["base_url"],
        openai_proxy="",
        root_client=sync_client,
        client=sync_client.chat.completions,
        root_async_client=async_client,
        async_client=async_client.chat.completions,
    )
    # LangChain's metadata field separately inherits organization environment
    # values even when prebuilt SDK clients are supplied. Clear the inert field.
    model.openai_organization = None
    return model


@contextmanager
def provider_error_boundary():
    from src.credentials import current_credentials
    try:
        yield
    except Exception:
        if current_credentials.get() is None:
            raise
        raise ValueError("OpenAI request failed. Check your key and model access, or retry.") from None


class RequestModelMiddleware(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        with provider_error_boundary():
            return handler(request.override(model=request_model(request.model)))

    async def awrap_model_call(self, request, handler):
        with provider_error_boundary():
            return await handler(request.override(model=request_model(request.model)))


class CredentialScopedModel(BaseChatModel):
    """Route DeepAgents' internal summary/subagent model calls through BYOK too."""

    fallback: BaseChatModel = Field(exclude=True)

    @property
    def _llm_type(self):
        return "credential-scoped"

    def bind_tools(self, tools, **kwargs):
        return self.bind(_credential_tools=tools, _credential_tool_options=kwargs)

    def _target(self, kwargs):
        model = request_model(self.fallback)
        options = dict(kwargs)
        tools = options.pop("_credential_tools", None)
        tool_options = options.pop("_credential_tool_options", {})
        if tools is not None:
            bound = model.bind_tools(tools, **tool_options)
            while hasattr(bound, "bound") and hasattr(bound, "kwargs"):
                options = {**bound.kwargs, **options}
                bound = bound.bound
            model = bound
        return model, options

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        with provider_error_boundary():
            model, options = self._target(kwargs)
            return model._generate(messages, stop=stop, run_manager=run_manager, **options)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        with provider_error_boundary():
            model, options = self._target(kwargs)
            return await model._agenerate(messages, stop=stop, run_manager=run_manager, **options)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        with provider_error_boundary():
            model, options = self._target(kwargs)
            for chunk in model._stream(messages, stop=stop, run_manager=run_manager, **options):
                yield chunk if isinstance(chunk, ChatGenerationChunk) else ChatGenerationChunk(message=as_chunk(chunk))

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        with provider_error_boundary():
            model, options = self._target(kwargs)
            async for chunk in model._astream(messages, stop=stop, run_manager=run_manager, **options):
                yield chunk if isinstance(chunk, ChatGenerationChunk) else ChatGenerationChunk(message=as_chunk(chunk))


def as_chunk(message):
    if isinstance(message, AIMessageChunk):
        return message
    return AIMessageChunk(**message.model_dump(exclude={"type"}))
