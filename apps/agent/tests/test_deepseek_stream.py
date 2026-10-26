"""Fireworks empty deltas must not close AG-UI's in-progress UI tool call."""

import asyncio
import json

import pytest
from ag_ui.core import RunAgentInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessageChunk, HumanMessage, message_chunk_to_message
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.graph import END, START, MessagesState, StateGraph

from src.bounded_memory_saver import BoundedMemorySaver
from src.credentials import CredentialScopedAgent
from src.model import CredentialScopedModel, DEEPSEEK_DEPLOYMENT, ModelOutputIncompleteError


class ToolStreamModel(BaseChatModel):
    model_name: str = DEEPSEEK_DEPLOYMENT
    chunks: list[ChatGenerationChunk]

    @property
    def _llm_type(self):
        return "test-tool-stream"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        message = self.chunks[0].message
        generation_info = dict(self.chunks[0].generation_info or {})
        for chunk in self.chunks[1:]:
            message += chunk.message
            generation_info.update(chunk.generation_info or {})
        return ChatResult(generations=[ChatGeneration(
            message=message_chunk_to_message(message),
            generation_info=generation_info,
        )])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        yield from self.chunks

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        for chunk in self.chunks:
            yield chunk


def tool_chunks():
    def chunk(**kwargs):
        return ChatGenerationChunk(message=AIMessageChunk(content="", id="message", **kwargs))

    return [
        chunk(response_metadata={"model_provider": "openai"}),
        chunk(tool_call_chunks=[{"name": "generateSandboxedUi", "id": "call-ui", "index": 0, "args": ""}]),
        chunk(),
        chunk(tool_call_chunks=[{"name": None, "id": None, "index": 0, "args": '{"html":"<p>Ready</p>",'}]),
        chunk(response_metadata={"model_provider": "openai"}),
        chunk(tool_call_chunks=[{"name": None, "id": None, "index": 0, "args": '"jsExpressions":["init()"]}'}]),
        ChatGenerationChunk(
            message=AIMessageChunk(content="", id="message", response_metadata={"model_provider": "openai"}),
            generation_info={"finish_reason": "tool_calls"},
        ),
        chunk(usage_metadata={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}, chunk_position="last"),
    ]


@pytest.mark.parametrize("streaming_async", [False, True])
@pytest.mark.parametrize("model_name", [DEEPSEEK_DEPLOYMENT, "gpt-6-luna", "claude-sonnet-5.5"])
def test_filters_only_deepseek_empty_deltas_preserving_arguments_and_terminal_metadata(model_name, streaming_async):
    original = tool_chunks()
    model = ToolStreamModel(model_name=model_name, chunks=original)
    scoped = CredentialScopedModel(fallback=model, resolved_model=model)

    async def collect():
        return [chunk async for chunk in scoped._astream([HumanMessage(content="Build UI")])]

    chunks = asyncio.run(collect()) if streaming_async else list(scoped._stream([HumanMessage(content="Build UI")]))
    expected = [original[index] for index in [1, 3, 5, 6, 7]] if model_name == DEEPSEEK_DEPLOYMENT else original
    assert chunks == expected
    combined = chunks[0].message
    for chunk in chunks[1:]:
        combined += chunk.message
    assert combined.tool_calls[0]["args"] == {"html": "<p>Ready</p>", "jsExpressions": ["init()"]}
    assert chunks[-2].generation_info["finish_reason"] == "tool_calls"
    assert chunks[-1].message.usage_metadata["total_tokens"] == 30
    assert chunks[-1].message.chunk_position == "last"


@pytest.mark.parametrize("truncated", [False, True])
def test_deepseek_ui_tool_arguments_reach_agui_or_report_truncation(truncated):
    chunks = tool_chunks()
    if truncated:
        chunks[-2].generation_info["finish_reason"] = "length"
    model = ToolStreamModel(chunks=chunks)
    scoped = CredentialScopedModel(fallback=model, resolved_model=model)

    async def answer(state):
        combined = None
        async for chunk in scoped.astream(state["messages"]):
            combined = chunk if combined is None else combined + chunk
        return {"messages": [message_chunk_to_message(combined)]}

    graph = StateGraph(MessagesState)
    graph.add_node("answer", answer)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    adapter = CredentialScopedAgent(name="test", graph=graph.compile(checkpointer=BoundedMemorySaver()))

    async def collect():
        return [event async for event in adapter.run(RunAgentInput(
            thread_id="test-thread", run_id="test-run",
            messages=[{"id": "user", "role": "user", "content": "Build UI"}],
            state={}, tools=[], context=[], forwarded_props={},
        ))]

    events = asyncio.run(collect())
    if truncated:
        assert events[-1].type == "RUN_ERROR"
        assert events[-1].code == "MODEL_OUTPUT_INCOMPLETE"
        assert "output limit" in events[-1].message
        assert not any(event.type == "RUN_FINISHED" for event in events)
        return
    tool_events = [event for event in events if event.type.startswith("TOOL_CALL_")]
    assert [event.type for event in tool_events] == [
        "TOOL_CALL_START", "TOOL_CALL_ARGS", "TOOL_CALL_ARGS", "TOOL_CALL_END",
    ]
    assert tool_events[0].tool_call_name == "generateSandboxedUi"
    assert json.loads("".join(event.delta for event in tool_events if event.type == "TOOL_CALL_ARGS")) == {
        "html": "<p>Ready</p>", "jsExpressions": ["init()"],
    }
    assert all(event.tool_call_id == "call-ui" for event in tool_events)


@pytest.mark.parametrize("streaming_async", [False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("metadata_location", ["message", "generation"])
def test_deepseek_truncation_raises_instead_of_finishing_successfully(streaming, streaming_async, metadata_location):
    metadata = {"finish_reason": "length"}
    chunks = [ChatGenerationChunk(message=AIMessageChunk(
        content="unfinished", response_metadata=metadata if metadata_location == "message" else {},
    ), generation_info=metadata if metadata_location == "generation" else None)]
    model = ToolStreamModel(chunks=chunks)
    scoped = CredentialScopedModel(fallback=model, resolved_model=model)

    async def collect():
        if streaming:
            return [chunk async for chunk in scoped._astream([HumanMessage(content="Build UI")])]
        return await scoped._agenerate([HumanMessage(content="Build UI")])

    with pytest.raises(ModelOutputIncompleteError, match="output limit"):
        if streaming_async:
            asyncio.run(collect())
        elif streaming:
            list(scoped._stream([HumanMessage(content="Build UI")]))
        else:
            scoped._generate([HumanMessage(content="Build UI")])
