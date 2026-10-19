"""Unit tests for Azure AI Foundry Entra ID authentication helpers."""

from __future__ import annotations

import pytest

import src.azure_auth as azure_auth
from src.azure_auth import (
    AZURE_COGNITIVE_SERVICES_SCOPE,
    DEFAULT_AZURE_AI_FOUNDRY_ENDPOINT,
    get_azure_bearer_token,
    get_azure_token_provider,
    get_decision_endpoint,
    get_foundry_endpoint,
    get_foundry_openai_base_url,
    is_azure_foundry_enabled,
)


def test_get_foundry_endpoint_defaults_and_strips_trailing_slash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENDPOINT", raising=False)
    assert get_foundry_endpoint() == "https://ai-isarar-2855.services.ai.azure.com"

    monkeypatch.setenv(
        "AZURE_AI_FOUNDRY_ENDPOINT",
        "https://custom-foundry.services.ai.azure.com///",
    )
    assert get_foundry_endpoint() == "https://custom-foundry.services.ai.azure.com"

    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENDPOINT", "   ")
    assert get_foundry_endpoint() == DEFAULT_AZURE_AI_FOUNDRY_ENDPOINT


def test_get_foundry_openai_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENDPOINT", raising=False)
    assert (
        get_foundry_openai_base_url()
        == "https://ai-isarar-2855.services.ai.azure.com/openai/v1"
    )


def test_get_decision_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENDPOINT", raising=False)
    monkeypatch.delenv("DECISION_ENDPOINT", raising=False)
    assert (
        get_decision_endpoint()
        == "https://ai-isarar-2855.services.ai.azure.com/providers/microsoft/v1/systemone"
    )

    monkeypatch.setenv(
        "DECISION_ENDPOINT",
        "https://override.services.ai.azure.com/providers/microsoft/v1/systemone",
    )
    assert (
        get_decision_endpoint()
        == "https://override.services.ai.azure.com/providers/microsoft/v1/systemone"
    )


@pytest.mark.parametrize(
    ("env_val", "expected"),
    [
        (None, True),
        ("", True),
        ("true", True),
        ("TRUE", True),
        ("1", True),
        ("false", False),
        ("FALSE", False),
        ("0", False),
        ("no", False),
    ],
)
def test_is_azure_foundry_enabled(
    monkeypatch: pytest.MonkeyPatch,
    env_val: str | None,
    expected: bool,
) -> None:
    if env_val is None:
        monkeypatch.delenv("AZURE_AI_FOUNDRY_ENABLED", raising=False)
    else:
        monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", env_val)
    assert is_azure_foundry_enabled() is expected


def test_get_azure_token_provider_uses_cognitive_services_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel_cred = object()
    recorded: list[tuple[object, str]] = []

    monkeypatch.setattr(azure_auth, "build_azure_credential", lambda: sentinel_cred)

    def fake_bearer_provider(credential: object, scope: str):
        recorded.append((credential, scope))
        return lambda: "mock-entra-bearer-token"

    monkeypatch.setattr(
        azure_auth, "get_bearer_token_provider", fake_bearer_provider
    )

    provider = get_azure_token_provider()
    assert callable(provider)
    assert provider() == "mock-entra-bearer-token"
    assert get_azure_bearer_token() == "mock-entra-bearer-token"
    assert recorded == [
        (sentinel_cred, AZURE_COGNITIVE_SERVICES_SCOPE),
        (sentinel_cred, AZURE_COGNITIVE_SERVICES_SCOPE),
    ]
