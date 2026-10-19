"""Public internet grounding via Microsoft Web IQ (/v3/search/web)."""

from __future__ import annotations

import os
from typing import Any

import httpx
from langchain.tools import tool

WEBIQ_SEARCH_URL = "https://api.microsoft.ai/v3/search/web"
WEBIQ_HOST = "api.microsoft.ai"
VALID_CONTENT_FORMATS = {"passage", "text", "html", "markdown"}
VALID_SAFE_SEARCH = {"off", "strict"}
MAX_QUERY_LENGTH = 1000
MIN_RESULTS = 1
MAX_RESULTS = 50
DEFAULT_MAX_LENGTH = 3000
DEFAULT_TIMEOUT_SECONDS = 15.0


def get_webiq_endpoint() -> str:
    """Resolve the Web IQ endpoint URL from environment or default."""
    endpoint = (
        os.environ.get("WEBIQ_ENDPOINT", "").strip()
        or os.environ.get("WEBIQ_SEARCH_URL", "").strip()
        or WEBIQ_SEARCH_URL
    )
    return endpoint


def _sanitize_error(message: str, api_key: str = "") -> str:
    """Ensure the Web IQ API key is never included in error output."""
    sanitized = str(message)
    if api_key:
        sanitized = sanitized.replace(api_key, "[REDACTED]")
    env_key = os.environ.get("WEBIQ_API_KEY", "").strip()
    if env_key:
        sanitized = sanitized.replace(env_key, "[REDACTED]")
    return sanitized


def _validate_search_params(
    query: str,
    max_results: int = 5,
    language: str = "en",
    region: str = "US",
    content_format: str = "passage",
    max_length: int = DEFAULT_MAX_LENGTH,
    safe_search: str = "strict",
) -> tuple[str, int, str, str, str, int, str]:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must not be empty")
    cleaned_query = query.strip()[:MAX_QUERY_LENGTH]

    if isinstance(max_results, bool) or not isinstance(max_results, int):
        raise ValueError("max_results must be an integer between 1 and 50")
    bounded_max_results = max(MIN_RESULTS, min(MAX_RESULTS, max_results))

    normalized_language = (language if isinstance(language, str) else "").strip().lower()
    if len(normalized_language) != 2 or not normalized_language.isalpha():
        raise ValueError("language must be a 2-letter ISO 639-1 code")

    normalized_region = (region if isinstance(region, str) else "").strip().upper()
    if len(normalized_region) != 2 or not normalized_region.isalpha():
        raise ValueError("region must be a 2-letter region code")

    if content_format not in VALID_CONTENT_FORMATS:
        raise ValueError(f"content_format must be one of {sorted(VALID_CONTENT_FORMATS)}")

    if safe_search not in VALID_SAFE_SEARCH:
        raise ValueError(f"safe_search must be one of {sorted(VALID_SAFE_SEARCH)}")

    if isinstance(max_length, bool) or not isinstance(max_length, int) or max_length < 1:
        raise ValueError("max_length must be a positive integer")

    return (
        cleaned_query,
        bounded_max_results,
        normalized_language,
        normalized_region,
        content_format,
        max_length,
        safe_search,
    )


def normalize_web_result(item: dict[str, Any]) -> dict[str, str]:
    """Normalize a single Web IQ result item, supplying empty defaults for omitted fields."""
    content = item.get("content") or item.get("snippet") or ""
    crawled_at = item.get("crawledAt") or ""
    last_updated_at = item.get("lastUpdatedAt") or ""
    date = item.get("date") or last_updated_at or crawled_at or ""
    return {
        "title": item.get("title") or "",
        "url": item.get("url") or "",
        "domain": item.get("domain") or "",
        "content": content,
        "snippet": item.get("snippet") or content,
        "date": date,
        "crawled_at": crawled_at,
        "last_updated_at": last_updated_at,
        "language": item.get("language") or "",
    }


def search_web_iq(
    query: str,
    max_results: int = 5,
    language: str = "en",
    region: str = "US",
    content_format: str = "passage",
    max_length: int = DEFAULT_MAX_LENGTH,
    safe_search: str = "strict",
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> dict[str, Any]:
    """Execute a POST /v3/search/web request against Microsoft Web IQ."""
    (
        cleaned_query,
        bounded_max_results,
        normalized_language,
        normalized_region,
        validated_format,
        validated_max_length,
        validated_safe_search,
    ) = _validate_search_params(
        query=query,
        max_results=max_results,
        language=language,
        region=region,
        content_format=content_format,
        max_length=max_length,
        safe_search=safe_search,
    )

    resolved_key = (
        api_key if api_key is not None else os.environ.get("WEBIQ_API_KEY", "")
    ).strip()
    if not resolved_key:
        return {
            "ok": False,
            "source": "Microsoft Web IQ",
            "status": "unavailable",
            "query": cleaned_query,
            "error": "missing_webiq_api_key",
            "message": "WEBIQ_API_KEY is not configured in the agent environment.",
            "results": [],
        }

    url = get_webiq_endpoint()
    headers = {
        "host": WEBIQ_HOST,
        "x-apikey": resolved_key,
        "content-type": "application/json",
    }
    payload = {
        "query": cleaned_query,
        "maxResults": bounded_max_results,
        "language": normalized_language,
        "region": normalized_region,
        "contentFormat": validated_format,
        "maxLength": validated_max_length,
        "safeSearch": validated_safe_search,
    }

    try:
        if client is not None:
            response = client.post(url, headers=headers, json=payload)
        else:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected response format from Microsoft Web IQ.")
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        return {
            "ok": False,
            "source": "Microsoft Web IQ",
            "status": "unavailable",
            "query": cleaned_query,
            "error": f"Microsoft Web IQ request failed with HTTP {status_code}.",
            "results": [],
        }
    except Exception as exc:
        return {
            "ok": False,
            "source": "Microsoft Web IQ",
            "status": "unavailable",
            "query": cleaned_query,
            "error": _sanitize_error(f"Microsoft Web IQ request failed: {exc}", resolved_key),
            "results": [],
        }

    query_signals = data.get("querySignals")
    if not isinstance(query_signals, dict):
        query_signals = {}

    raw_results = data.get("webResults")
    if not isinstance(raw_results, list):
        raw_results = []

    normalized_results = [
        normalize_web_result(item) for item in raw_results if isinstance(item, dict)
    ]

    return {
        "ok": True,
        "source": "Microsoft Web IQ",
        "query": cleaned_query,
        "freshness": bool(query_signals.get("freshness", False)),
        "risk_level": data.get("riskLevel") or "",
        "trace_id": data.get("traceId") or "",
        "results": normalized_results,
    }


@tool
def web_search(
    query: str,
    max_results: int = 5,
    language: str = "en",
    region: str = "US",
) -> dict[str, Any]:
    """Search the public internet using Microsoft Web IQ (/v3/search/web) for current, real-world grounding and citation-ready passages."""
    return search_web_iq(
        query=query,
        max_results=max_results,
        language=language,
        region=region,
    )
