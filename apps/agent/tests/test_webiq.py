"""Unit tests for Microsoft Web IQ public internet grounding."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from src.webiq import search_web_iq, web_search


def test_missing_webiq_api_key_returns_structured_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("WEBIQ_API_KEY", raising=False)

    direct = search_web_iq("azure foundry updates")
    assert direct["ok"] is False
    assert direct["error"] == "missing_webiq_api_key"
    assert direct["results"] == []

    tool_result = web_search.invoke({"query": "azure foundry updates"})
    assert tool_result["ok"] is False
    assert tool_result["error"] == "missing_webiq_api_key"
    assert tool_result["results"] == []


def test_search_web_iq_sends_required_headers_payload_clamps_results_and_normalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEBIQ_API_KEY", "webiq-secret-123")
    monkeypatch.delenv("WEBIQ_ENDPOINT", raising=False)
    monkeypatch.delenv("WEBIQ_SEARCH_URL", raising=False)

    captured_calls: list[dict[str, Any]] = []

    def fake_post(url: str, *, headers: dict[str, str], json: dict[str, Any], **kwargs: Any) -> httpx.Response:
        captured_calls.append({"url": url, "headers": headers, "json": json})
        request = httpx.Request("POST", url, headers=headers, json=json)
        return httpx.Response(
            200,
            request=request,
            json={
                "querySignals": {"freshness": True},
                "riskLevel": "low",
                "traceId": "trace-abc-123",
                "webResults": [
                    {
                        "title": "Microsoft Web IQ Overview",
                        "url": "https://webiq.microsoft.ai/docs",
                        "domain": "webiq.microsoft.ai",
                        "content": "Grounded web passages for AI agents.",
                        "crawledAt": "2026-10-18T12:00:00Z",
                        "lastUpdatedAt": "2026-10-19T08:30:00Z",
                        "language": "en",
                    },
                    {
                        "title": "Minimal Result Omitting Optional Fields",
                        "url": "https://example.com/minimal",
                    },
                ],
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)

    # Test clamping upper bound (> 50 -> 50)
    res_high = search_web_iq("microsoft web iq", max_results=999)
    assert len(captured_calls) == 1
    call_high = captured_calls[0]
    assert call_high["url"] == "https://api.microsoft.ai/v3/search/web"
    assert call_high["headers"]["x-apikey"] == "webiq-secret-123"
    assert call_high["headers"]["host"] == "api.microsoft.ai"
    assert call_high["json"]["contentFormat"] == "passage"
    assert call_high["json"]["maxLength"] == 3000
    assert call_high["json"]["safeSearch"] == "strict"
    assert call_high["json"]["maxResults"] == 50

    assert res_high["ok"] is True
    assert res_high["freshness"] is True
    assert res_high["trace_id"] == "trace-abc-123"
    assert len(res_high["results"]) == 2

    first = res_high["results"][0]
    assert first["title"] == "Microsoft Web IQ Overview"
    assert first["url"] == "https://webiq.microsoft.ai/docs"
    assert first["content"] == "Grounded web passages for AI agents."
    assert first["snippet"] == "Grounded web passages for AI agents."
    assert first["date"] == "2026-10-19T08:30:00Z"

    second = res_high["results"][1]
    assert second["title"] == "Minimal Result Omitting Optional Fields"
    assert second["url"] == "https://example.com/minimal"
    assert second["snippet"] == ""
    assert second["content"] == ""
    assert second["date"] == ""
    assert second["crawled_at"] == ""
    assert second["last_updated_at"] == ""

    # Test clamping lower bound (< 1 -> 1) via the web_search tool
    web_search.invoke({"query": "microsoft web iq", "max_results": -10})
    assert captured_calls[1]["json"]["maxResults"] == 1


def test_http_errors_and_exceptions_never_leak_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret_key = "super-sensitive-webiq-key-999"
    monkeypatch.setenv("WEBIQ_API_KEY", secret_key)

    def failing_status(url: str, **kwargs: Any) -> httpx.Response:
        request = httpx.Request("POST", url)
        return httpx.Response(
            403,
            request=request,
            text=f"Forbidden for key {secret_key}",
        )

    monkeypatch.setattr(httpx, "post", failing_status)
    status_result = web_search.invoke({"query": "test status error"})
    assert status_result["ok"] is False
    assert secret_key not in repr(status_result)

    def failing_exception(url: str, **kwargs: Any) -> httpx.Response:
        raise httpx.ConnectError(f"Connection failed using header x-apikey={secret_key}")

    monkeypatch.setattr(httpx, "post", failing_exception)
    exc_result = web_search.invoke({"query": "test network error"})
    assert exc_result["ok"] is False
    assert secret_key not in repr(exc_result)
