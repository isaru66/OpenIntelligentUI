import pytest
from langchain_core.messages import HumanMessage, AIMessage
from src.visualization_router import (
    decision_from_response,
    routing_input,
    routed_request,
)
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import SystemMessage


def response(choice):
    return {
        "answers": {
            "visualization": {
                "type": "choice",
                "choice": choice,
                "confidence": 0.9,
                "probabilities": {choice: 0.9},
            }
        }
    }


@pytest.mark.parametrize(
    ("choice", "renderer"),
    [
        ("table", "a2ui"),
        ("line_chart", "open_generative_ui"),
        ("map", "open_generative_ui"),
        ("animated_route", "open_generative_ui"),
        ("interactive_diagram", "open_generative_ui"),
        ("text", "text"),
    ],
)
def test_valid_decisions_map_to_exact_renderer(choice, renderer):
    assert decision_from_response(response(choice))["renderer"] == renderer


@pytest.mark.parametrize(
    "raw",
    [{}, response("invented"), {"answers": {"visualization": {"choice": "table"}}}],
)
def test_bad_decisions_fail_loudly(raw):
    with pytest.raises(ValueError, match="Jev"):
        decision_from_response(raw)


def test_continuation_reuses_decision_but_new_human_reroutes():
    state = {
        "messages": [HumanMessage(content="table", id="one")],
        "visualization_turn": "one",
        "visualization_decision": decision_from_response(response("table")),
    }
    assert routing_input(state) is None
    state["messages"].append(AIMessage(content="done"))
    assert routing_input(state) is None
    state["messages"].append(HumanMessage(content="now chart it", id="two"))
    turn, context = routing_input(state)
    assert turn == "two"
    assert context[-1]["content"] == "now chart it"


@pytest.mark.parametrize(
    ("choice", "allowed"),
    [
        ("table", "send_a2ui_json_to_client"),
        ("line_chart", "generateSandboxedUi"),
        ("map", "generateSandboxedUi"),
        ("animated_route", "generateSandboxedUi"),
        ("text", None),
    ],
)
def test_route_filters_renderers_preserving_data_tools(choice, allowed):
    tools = [
        {"name": n}
        for n in [
            "render_a2ui",
            "send_a2ui_json_to_client",
            "generate_a2ui",
            "generateSandboxedUi",
            "barChart",
            "pieChart",
            "query_data",
        ]
    ]
    request = ModelRequest(
        model=None,
        messages=[],
        tools=tools,
        system_message=SystemMessage(content="base"),
        state={"visualization_decision": decision_from_response(response(choice))},
    )
    result = routed_request(request)
    names = {t["name"] for t in result.tools}
    assert "query_data" in names
    assert ("generateSandboxedUi" in names) == (allowed == "generateSandboxedUi")
    assert ("send_a2ui_json_to_client" in names) == (
        allowed == "send_a2ui_json_to_client"
    )
    # @copilotkit/runtime's locked A2UI middleware injects render_a2ui.
    assert ("render_a2ui" in names) == (choice == "table")
    assert "barChart" not in names and "pieChart" not in names
    if choice == "map":
        assert "basemap.nationalmap.gov" in result.system_message.content
        assert "USGS attribution" in result.system_message.content
        assert "coverage limits" in result.system_message.content


def test_default_azure_foundry_router_options_and_url(monkeypatch):
    import src.visualization_router as router

    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENABLED", raising=False)
    monkeypatch.delenv("AZURE_AI_FOUNDRY_ENDPOINT", raising=False)
    monkeypatch.delenv("DECISION_ENDPOINT", raising=False)
    monkeypatch.delenv("AZURE_DECISION_DEPLOYMENT", raising=False)
    monkeypatch.delenv("DECISION_MODEL", raising=False)
    monkeypatch.delenv("JEV_MODEL", raising=False)
    monkeypatch.setattr(router, "get_azure_bearer_token", lambda: "entra-decision-token")

    assert (
        router.get_router_url()
        == "https://ai-isarar-2855.services.ai.azure.com/providers/microsoft/v1/systemone"
    )
    options = router.request_options([{"role": "human", "content": "Chart sales"}])
    assert options["json"]["model"] == "Decision-1"
    assert options["headers"]["Authorization"].endswith("entra-decision-token")


def test_legacy_and_byok_router_options_and_url(monkeypatch):
    from src.credentials import Credentials, current_credentials
    import src.visualization_router as router

    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "false")
    monkeypatch.setenv("TYPESAFE_API_KEY", "legacy-typesafe-key")
    monkeypatch.delenv("JEV_MODEL", raising=False)

    assert router.get_router_url() == router.LEGACY_JEV_URL
    legacy_opts = router.request_options([])
    assert legacy_opts["json"]["model"] == "jev-latest"
    assert legacy_opts["headers"]["Authorization"].endswith("legacy-typesafe-key")

    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")
    token = current_credentials.set(Credentials("byok-openai", "byok-jev"))
    try:
        assert router.get_router_url() == router.LEGACY_JEV_URL
        byok_opts = router.request_options([])
        assert byok_opts["json"]["model"] == "jev-latest"
        assert byok_opts["headers"]["Authorization"].endswith("byok-jev")
    finally:
        current_credentials.reset(token)


def test_missing_key_is_actionable(monkeypatch):
    from src.visualization_router import request_options

    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "false")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
        request_options([])


def test_provider_errors_do_not_expose_response_body():
    import httpx
    from src.visualization_router import parse_response

    with pytest.raises(ValueError, match="HTTP 401") as error:
        parse_response(httpx.Response(401, text="sensitive provider details"))
    assert "sensitive" not in str(error.value)


def test_timeout_is_actionable_without_secret_headers(monkeypatch):
    import httpx
    import src.visualization_router as router

    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "false")
    monkeypatch.setenv("TYPESAFE_API_KEY", "private-test-value")

    def timeout(*args, **kwargs):
        raise httpx.ReadTimeout("private-test-value")

    monkeypatch.setattr(httpx.Client, "post", timeout)
    with pytest.raises(ValueError, match="timed out") as error:
        router.route([])
    assert "private-test-value" not in str(error.value)


def test_context_excludes_system_and_tool_content_and_is_bounded():
    from langchain_core.messages import ToolMessage

    state = {
        "messages": [
            SystemMessage(content="secret system"),
            ToolMessage(content="tool payload", tool_call_id="x"),
            HumanMessage(content="a" * 20000, id="bounded"),
        ]
    }
    _, context = routing_input(state)
    assert len(context) == 1
    assert len(context[0]["content"]) == 6000


def test_real_graph_filters_injected_frontend_tools_and_routes_once(monkeypatch):
    import asyncio
    from deepagents import create_deep_agent
    from copilotkit import CopilotKitMiddleware
    from langchain_core.language_models.fake_chat_models import (
        FakeMessagesListChatModel,
    )
    from langgraph.checkpoint.memory import InMemorySaver
    import src.visualization_router as router

    bound = []
    calls = []

    class FakeModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            bound.append(
                {t.get("name") if isinstance(t, dict) else t.name for t in tools}
            )
            return self

    async def classify(context):
        calls.append(context)
        return decision_from_response(response("interactive_diagram"))

    monkeypatch.setattr(router, "aroute", classify)
    graph = create_deep_agent(
        model=FakeModel(responses=[AIMessage(content="Ready")]),
        middleware=[CopilotKitMiddleware(), router.JevVisualizationMiddleware()],
        checkpointer=InMemorySaver(),
    )

    async def run():
        config = {"configurable": {"thread_id": "routing-test"}}
        actions = [
            {
                "name": name,
                "description": name,
                "parameters": {"type": "object", "properties": {}},
            }
            for name in ["generateSandboxedUi", "render_a2ui", "send_a2ui_json_to_client", "barChart"]
        ]
        await graph.ainvoke(
            {
                "messages": [HumanMessage(content="Explain gears", id="one")],
                "copilotkit": {"actions": actions},
            },
            config,
        )
        await graph.ainvoke({"messages": []}, config)
        assert len(calls) == 1
        await graph.ainvoke(
            {"messages": [HumanMessage(content="Now explain torque", id="two")]}, config
        )
        assert len(calls) == 2

    asyncio.run(run())
    assert bound and all(
        "generateSandboxedUi" in tools
        and "render_a2ui" not in tools
        and "barChart" not in tools
        and "send_a2ui_json_to_client" not in tools
        for tools in bound
    )


def test_idless_continuation_has_stable_turn_key():
    state = {"messages": [HumanMessage(content="table")]}
    turn, _ = routing_input(state)
    state.update(
        visualization_turn=turn,
        visualization_decision=decision_from_response(response("table")),
    )
    state["messages"].append(AIMessage(content="done"))
    assert routing_input(state) is None
    state["messages"].append(HumanMessage(content="table"))
    assert routing_input(state)[0] != turn
