"""Chat model factory for the agent."""

import asyncio
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar

import anthropic
import httpx
import openai
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

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-6-luna"
BYOK_DEFAULT_MODEL = "chat-latest"

MAX_MODEL_RETRIES = 3
MODEL_RETRY_DELAYS = (2.0, 4.0, 8.0)
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

_NON_RETRYABLE_PROVIDER_ERRORS = (
    openai.BadRequestError,
    openai.AuthenticationError,
    openai.PermissionDeniedError,
    openai.NotFoundError,
    openai.UnprocessableEntityError,
    anthropic.BadRequestError,
    anthropic.AuthenticationError,
    anthropic.PermissionDeniedError,
    anthropic.NotFoundError,
    anthropic.UnprocessableEntityError,
)

_RETRYABLE_PROVIDER_ERRORS = (
    openai.RateLimitError,
    openai.APITimeoutError,
    openai.APIConnectionError,
    openai.InternalServerError,
    anthropic.RateLimitError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
    anthropic.InternalServerError,
    httpx.TimeoutException,
    httpx.TransportError,
)

_RETRYABLE_ERROR_CODES = frozenset(
    {
        "rate_limit_exceeded",
        "429",
        "too_many_requests",
        "server_error",
        "overloaded_error",
        "temporarily_unavailable",
        "timeout",
    }
)

_RETRYABLE_ERROR_MARKERS = (
    "rate limit",
    "rate_limit",
    "exceeded token rate limit",
    "too many requests",
    "429",
    "overloaded",
    "temporarily unavailable",
    "server error",
    "server_error",
    "timed out",
    "timeout",
)

_active_retry_counter: ContextVar[list[int] | None] = ContextVar(
    "_active_retry_counter", default=None
)

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


def is_retryable_model_error(exc: BaseException) -> bool:
    """Return True for rate-limit (HTTP 429 or SSE APIError) and transient provider errors."""
    if isinstance(exc, _NON_RETRYABLE_PROVIDER_ERRORS):
        return False
    if isinstance(exc, _RETRYABLE_PROVIDER_ERRORS):
        return True
    status_code = getattr(exc, "status_code", None)
    if status_code in RETRYABLE_STATUS_CODES:
        return True
    if isinstance(exc, (openai.APIError, anthropic.APIError)):
        code = str(getattr(exc, "code", "") or "").strip().lower()
        if code in _RETRYABLE_ERROR_CODES:
            return True
        message = str(exc).lower()
        if any(marker in message for marker in _RETRYABLE_ERROR_MARKERS):
            return True
    return False


def _retry_delay_seconds(attempt: int) -> float:
    if attempt < len(MODEL_RETRY_DELAYS):
        return MODEL_RETRY_DELAYS[attempt]
    return MODEL_RETRY_DELAYS[-1]


def _chunk_has_payload(chunk: ChatGenerationChunk) -> bool:
    """Return False for initial metadata-only SSE chunks (e.g. response.created)."""
    msg = chunk.message
    if getattr(msg, "tool_call_chunks", None) or getattr(msg, "tool_calls", None):
        return True
    if getattr(msg, "chunk_position", None) == "last" or getattr(msg, "usage_metadata", None):
        return True
    content = getattr(msg, "content", None)
    if isinstance(content, str):
        return bool(content)
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str) and block:
                return True
            if isinstance(block, dict):
                block_type = block.get("type")
                if block.get("text") or block.get("arguments") or block.get("name"):
                    return True
                if block.get("refusal") or block.get("annotations"):
                    return True
                summary = block.get("summary")
                if isinstance(summary, list) and any(
                    isinstance(item, dict) and bool(item.get("text")) for item in summary
                ):
                    return True
                if block_type not in {None, "text", "reasoning"}:
                    return True
    return False


def _is_foundry_or_openai_model(model_name: str) -> bool:
    return model_name == "chat-latest" or model_name.startswith(FOUNDRY_MODEL_PREFIXES)


def build_model(*, allow_unconfigured: bool = False, model_name: str | None = None) -> BaseChatModel:
    model_name = (model_name or os.environ.get("LLM_MODEL", DEFAULT_MODEL)).strip()
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
            max_retries=0,
        )

    from langchain_openai import ChatOpenAI

    if is_azure_foundry_enabled():
        # gpt-6.1-sol rejects reasoning_effort="none" and chat completions reject
        # function tools with any other effort; all gpt-6* models use the Responses API.
        is_sol = model_name.startswith("gpt-6.1-sol")
        reasoning_effort = os.environ.get("LLM_REASONING_EFFORT", "none").strip()
        if is_sol and reasoning_effort in {"", "none"}:
            reasoning_effort = "low"
        use_responses_api = model_name.startswith("gpt-6") or os.environ.get(
            "LLM_USE_RESPONSES_API", ""
        ).strip().lower() in {
            "1",
            "true",
            "yes",
        }
        foundry_kwargs: dict = {
            "model": model_name,
            "base_url": get_foundry_openai_base_url(),
            "api_key": get_azure_token_provider(),
            "max_retries": 0,
        }
        if use_responses_api:
            foundry_kwargs["use_responses_api"] = True
            if reasoning_effort:
                foundry_kwargs["reasoning"] = {"effort": reasoning_effort}
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
    return ChatOpenAI(model=model_name, max_retries=0)


class UnconfiguredModel(BaseChatModel):
    """Compile a BYOK-only graph without constructing a provider with fake credentials."""

    @property
    def _llm_type(self):
        return "unconfigured"

    def _generate(self, *args, **kwargs):
        raise ValueError("Provider credentials are required. Add OpenAI and Jev keys.")

    def bind_tools(self, tools, **kwargs):
        return self


_selected_models: dict[str, BaseChatModel] = {}


def selected_model(fallback):
    """Honour the allowlisted x-ai-model choice; any unusable choice keeps the server default."""
    from src.selection import AI_MODELS, current_selection
    name = current_selection.get().ai_model
    if name not in AI_MODELS or name == os.environ.get("LLM_MODEL", DEFAULT_MODEL).strip():
        return fallback
    if name.startswith("claude-") and not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        return fallback
    if name not in _selected_models:
        try:
            _selected_models[name] = build_model(model_name=name)
        except ValueError:
            return fallback
    return _selected_models[name]


def request_model(fallback):
    from src.credentials import current_credentials
    credentials = current_credentials.get()
    if credentials is None:
        return selected_model(fallback)
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
        "max_retries": 0,
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
        max_retries=0,
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


def _scoped_model_for_request(model):
    base = model.fallback if isinstance(model, CredentialScopedModel) else model
    resolved = request_model(base)
    if isinstance(resolved, CredentialScopedModel):
        return resolved
    if isinstance(resolved, BaseChatModel):
        return CredentialScopedModel(fallback=base, resolved_model=resolved)
    return resolved


class RequestModelMiddleware(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        counter = [0]
        token = _active_retry_counter.set(counter)
        try:
            with provider_error_boundary():
                while True:
                    try:
                        return handler(
                            request.override(model=_scoped_model_for_request(request.model))
                        )
                    except Exception as exc:
                        if not is_retryable_model_error(exc) or counter[0] >= MAX_MODEL_RETRIES:
                            raise
                        delay = _retry_delay_seconds(counter[0])
                        counter[0] += 1
                        logger.warning(
                            "Model call failed (%s); retrying (%d/%d) in %.1fs",
                            exc,
                            counter[0],
                            MAX_MODEL_RETRIES,
                            delay,
                        )
                        time.sleep(delay)
        finally:
            _active_retry_counter.reset(token)

    async def awrap_model_call(self, request, handler):
        counter = [0]
        token = _active_retry_counter.set(counter)
        try:
            with provider_error_boundary():
                while True:
                    try:
                        return await handler(
                            request.override(model=_scoped_model_for_request(request.model))
                        )
                    except Exception as exc:
                        if not is_retryable_model_error(exc) or counter[0] >= MAX_MODEL_RETRIES:
                            raise
                        delay = _retry_delay_seconds(counter[0])
                        counter[0] += 1
                        logger.warning(
                            "Model call failed (%s); retrying (%d/%d) in %.1fs",
                            exc,
                            counter[0],
                            MAX_MODEL_RETRIES,
                            delay,
                        )
                        await asyncio.sleep(delay)
        finally:
            _active_retry_counter.reset(token)


class CredentialScopedModel(BaseChatModel):
    """Route DeepAgents' internal summary/subagent model calls through BYOK too."""

    fallback: BaseChatModel = Field(exclude=True)
    resolved_model: BaseChatModel | None = Field(default=None, exclude=True)

    @property
    def _llm_type(self):
        return "credential-scoped"

    def bind_tools(self, tools, **kwargs):
        return self.bind(_credential_tools=tools, _credential_tool_options=kwargs)

    def _target(self, kwargs):
        model = (
            self.resolved_model
            if self.resolved_model is not None
            else request_model(self.fallback)
        )
        while isinstance(model, CredentialScopedModel):
            model = (
                model.resolved_model
                if model.resolved_model is not None
                else model.fallback
            )
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
        counter = _active_retry_counter.get() or [0]
        with provider_error_boundary():
            while True:
                try:
                    model, options = self._target(kwargs)
                    return model._generate(
                        messages, stop=stop, run_manager=run_manager, **options
                    )
                except Exception as exc:
                    if not is_retryable_model_error(exc) or counter[0] >= MAX_MODEL_RETRIES:
                        raise
                    delay = _retry_delay_seconds(counter[0])
                    counter[0] += 1
                    logger.warning(
                        "Model generate failed (%s); retrying (%d/%d) in %.1fs",
                        exc,
                        counter[0],
                        MAX_MODEL_RETRIES,
                        delay,
                    )
                    time.sleep(delay)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        counter = _active_retry_counter.get() or [0]
        with provider_error_boundary():
            while True:
                try:
                    model, options = self._target(kwargs)
                    return await model._agenerate(
                        messages, stop=stop, run_manager=run_manager, **options
                    )
                except Exception as exc:
                    if not is_retryable_model_error(exc) or counter[0] >= MAX_MODEL_RETRIES:
                        raise
                    delay = _retry_delay_seconds(counter[0])
                    counter[0] += 1
                    logger.warning(
                        "Model agenerate failed (%s); retrying (%d/%d) in %.1fs",
                        exc,
                        counter[0],
                        MAX_MODEL_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        counter = _active_retry_counter.get() or [0]
        with provider_error_boundary():
            while True:
                pending_chunks: list[ChatGenerationChunk] = []
                yielded_payload = False
                try:
                    model, options = self._target(kwargs)
                    for raw_chunk in model._stream(
                        messages, stop=stop, run_manager=run_manager, **options
                    ):
                        chunk = (
                            raw_chunk
                            if isinstance(raw_chunk, ChatGenerationChunk)
                            else ChatGenerationChunk(message=as_chunk(raw_chunk))
                        )
                        if not yielded_payload:
                            if _chunk_has_payload(chunk):
                                yielded_payload = True
                                for pending in pending_chunks:
                                    yield pending
                                pending_chunks.clear()
                                yield chunk
                            else:
                                pending_chunks.append(chunk)
                        else:
                            yield chunk
                    if not yielded_payload:
                        for pending in pending_chunks:
                            yield pending
                    return
                except Exception as exc:
                    if (
                        yielded_payload
                        or not is_retryable_model_error(exc)
                        or counter[0] >= MAX_MODEL_RETRIES
                    ):
                        raise
                    delay = _retry_delay_seconds(counter[0])
                    counter[0] += 1
                    logger.warning(
                        "Model stream failed before payload (%s); retrying (%d/%d) in %.1fs",
                        exc,
                        counter[0],
                        MAX_MODEL_RETRIES,
                        delay,
                    )
                    time.sleep(delay)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        counter = _active_retry_counter.get() or [0]
        with provider_error_boundary():
            while True:
                pending_chunks: list[ChatGenerationChunk] = []
                yielded_payload = False
                try:
                    model, options = self._target(kwargs)
                    async for raw_chunk in model._astream(
                        messages, stop=stop, run_manager=run_manager, **options
                    ):
                        chunk = (
                            raw_chunk
                            if isinstance(raw_chunk, ChatGenerationChunk)
                            else ChatGenerationChunk(message=as_chunk(raw_chunk))
                        )
                        if not yielded_payload:
                            if _chunk_has_payload(chunk):
                                yielded_payload = True
                                for pending in pending_chunks:
                                    yield pending
                                pending_chunks.clear()
                                yield chunk
                            else:
                                pending_chunks.append(chunk)
                        else:
                            yield chunk
                    if not yielded_payload:
                        for pending in pending_chunks:
                            yield pending
                    return
                except Exception as exc:
                    if (
                        yielded_payload
                        or not is_retryable_model_error(exc)
                        or counter[0] >= MAX_MODEL_RETRIES
                    ):
                        raise
                    delay = _retry_delay_seconds(counter[0])
                    counter[0] += 1
                    logger.warning(
                        "Model astream failed before payload (%s); retrying (%d/%d) in %.1fs",
                        exc,
                        counter[0],
                        MAX_MODEL_RETRIES,
                        delay,
                    )
                    await asyncio.sleep(delay)


def as_chunk(message):
    if isinstance(message, AIMessageChunk):
        return message
    return AIMessageChunk(**message.model_dump(exclude={"type"}))
