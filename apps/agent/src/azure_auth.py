"""Entra ID authentication helpers for Azure AI Foundry."""

from __future__ import annotations

import os
from typing import Callable

from azure.identity import (
    AzureCliCredential,
    ChainedTokenCredential,
    DefaultAzureCredential,
    get_bearer_token_provider,
)

AZURE_COGNITIVE_SERVICES_SCOPE = "https://cognitiveservices.azure.com/.default"
DEFAULT_AZURE_AI_FOUNDRY_RESOURCE_ID = (
    "/subscriptions/79e1d757-ecdb-4dc3-b0b4-035bac76053d"
    "/resourceGroups/aifoundary-resources"
    "/providers/Microsoft.CognitiveServices/accounts/ai-isarar-2855"
)
DEFAULT_AZURE_AI_FOUNDRY_ENDPOINT = "https://ai-isarar-2855.services.ai.azure.com"
DEFAULT_AZURE_SUBSCRIPTION_ID = "79e1d757-ecdb-4dc3-b0b4-035bac76053d"
DEFAULT_AZURE_TENANT_ID = "ddcbdc96-6162-4d91-bb0d-066343049ce1"


def get_foundry_endpoint() -> str:
    """Return the configured Azure AI Foundry base endpoint without a trailing slash."""
    endpoint = (
        os.environ.get("AZURE_AI_FOUNDRY_ENDPOINT", DEFAULT_AZURE_AI_FOUNDRY_ENDPOINT)
        .strip()
        .rstrip("/")
    )
    return endpoint or DEFAULT_AZURE_AI_FOUNDRY_ENDPOINT


def get_foundry_openai_base_url() -> str:
    """Return the OpenAI-compatible v1 base URL for Azure AI Foundry."""
    return f"{get_foundry_endpoint()}/openai/v1"


def get_decision_endpoint() -> str:
    """Return the SystemOne decision endpoint URL."""
    explicit = os.environ.get("DECISION_ENDPOINT", "").strip()
    if explicit:
        return explicit
    return f"{get_foundry_endpoint()}/providers/microsoft/v1/systemone"


def is_azure_foundry_enabled() -> bool:
    """Return True unless AZURE_AI_FOUNDRY_ENABLED explicitly disables Foundry."""
    raw = os.environ.get("AZURE_AI_FOUNDRY_ENABLED", "true").strip().lower()
    return raw not in {"0", "false", "no"}


def build_azure_credential() -> ChainedTokenCredential:
    """Construct a ChainedTokenCredential targeting the Azure AI Foundry subscription and tenant."""
    subscription_id = (
        os.environ.get("AZURE_SUBSCRIPTION_ID", DEFAULT_AZURE_SUBSCRIPTION_ID).strip()
        or DEFAULT_AZURE_SUBSCRIPTION_ID
    )
    tenant_id = (
        os.environ.get("AZURE_TENANT_ID", DEFAULT_AZURE_TENANT_ID).strip()
        or DEFAULT_AZURE_TENANT_ID
    )
    cli_by_subscription = AzureCliCredential(subscription=subscription_id)
    cli_by_tenant = AzureCliCredential(tenant_id=tenant_id)
    default_credential = DefaultAzureCredential(
        exclude_cli_credential=True,
        interactive_browser_tenant_id=tenant_id,
    )
    return ChainedTokenCredential(
        cli_by_subscription,
        cli_by_tenant,
        default_credential,
    )


def get_azure_token_provider() -> Callable[[], str]:
    """Return a callable bearer token provider for Azure Cognitive Services."""
    return get_bearer_token_provider(
        build_azure_credential(),
        AZURE_COGNITIVE_SERVICES_SCOPE,
    )


def get_azure_bearer_token() -> str:
    """Acquire and return a bearer token string for Azure Cognitive Services."""
    token_provider = get_azure_token_provider()
    return token_provider()
