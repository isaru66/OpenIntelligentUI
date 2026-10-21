import asyncio
import json
import os

import httpx
import pytest


def test_credentials_feature_exists():
    from src import model
    assert hasattr(model, 'RequestModelMiddleware')


def test_headers_validate_without_disclosing_values():
    from src.credentials import parse_credentials
    assert parse_credentials([]) is None
    keys = parse_credentials([(b'x-openai-api-key', b' openai-one '), (b'x-jev-api-key', b' jev-one ')])
    assert keys.openai == 'openai-one'
    assert keys.jev == 'jev-one'
    assert 'openai-one' not in repr(keys)
    for value in [b'', b'foo bar', b'bad\nkey', b'\x80', b'a' * 4097]:
        with pytest.raises(ValueError, match='invalid_keys'):
            parse_credentials([(b'x-openai-api-key', value), (b'x-jev-api-key', b'jev')])
    with pytest.raises(ValueError):
        parse_credentials([(b'x-openai-api-key', b'only')])


def test_concurrent_streams_isolate_keys_and_reset_on_cancellation():
    from src.credentials import CredentialsMiddleware, current_credentials
    async def exercise():
        entered = asyncio.Event()
        count = 0
        observed = []
        async def inner(scope, receive, send):
            nonlocal count
            assert not any(k.startswith(b'x-openai') or k.startswith(b'x-jev') for k, _ in scope['headers'])
            count += 1
            if count == 2:
                entered.set()
            await entered.wait()
            key = current_credentials.get().openai
            observed.append(key)
            await asyncio.sleep(0)
            assert current_credentials.get().openai == key
            if current_credentials.get().openai == 'cancel':
                raise asyncio.CancelledError
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'ok'})
        app = CredentialsMiddleware(inner)
        async def run(key):
            scope = {'type': 'http', 'path': '/', 'headers': [(b'x-openai-api-key', key.encode()), (b'x-jev-api-key', b'jev')]}
            async def receive():
                return {'type': 'http.disconnect'}
            async def send(message):
                pass
            try:
                await app(scope, receive, send)
            except asyncio.CancelledError:
                pass
            assert current_credentials.get() is None
        await asyncio.gather(run('one'), run('cancel'))
        assert sorted(observed) == ['cancel', 'one']
    asyncio.run(exercise())


def test_concurrent_shared_streams_keep_effort_for_middleware_and_internal_calls(monkeypatch):
    from langchain.agents.middleware import ModelRequest
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from src.credentials import CredentialsMiddleware
    from src.selection import Selection, current_selection
    import src.model as models

    models._selected_models.clear()
    fallback = FakeMessagesListChatModel(responses=[AIMessage(content="fallback")])
    selected = {
        effort: FakeMessagesListChatModel(responses=[AIMessage(content=effort)])
        for effort in ["medium", "max"]
    }
    monkeypatch.setattr(models, "build_model", lambda **kw: selected[kw["reasoning_effort"]])

    async def exercise():
        entered = asyncio.Event()
        count = 0
        observed = []
        scoped = models.CredentialScopedModel(fallback=fallback)
        async def inner(scope, receive, send):
            nonlocal count
            count += 1
            if count == 2:
                entered.set()
            await entered.wait()
            effort = current_selection.get().reasoning_effort
            assert (await scoped.ainvoke("internal summary")).content == effort
            request = ModelRequest(
                model=scoped, messages=[HumanMessage(content="hi")], tools=[],
                system_message=None, tool_choice=None, state={}, runtime=None,
            )
            async def handler(request):
                target, _ = request.model._target({})
                assert target is selected[effort]
                return effort
            assert await models.RequestModelMiddleware().awrap_model_call(request, handler) == effort
            await asyncio.sleep(0)
            assert current_selection.get().reasoning_effort == effort
            observed.append(effort)
            if effort == "max":
                raise asyncio.CancelledError
        async def run(effort):
            scope = {"type": "http", "path": "/stream", "headers": [
                (b"x-ai-model", b"gpt-6-luna"), (b"x-reasoning-effort", effort.encode()),
            ]}
            async def receive():
                return {"type": "http.disconnect"}
            async def send(message):
                pass
            try:
                await CredentialsMiddleware(inner)(scope, receive, send)
            except asyncio.CancelledError:
                pass
            assert current_selection.get() == Selection()
        await asyncio.gather(run("medium"), run("max"))
        assert sorted(observed) == ["max", "medium"]
    try:
        asyncio.run(exercise())
    finally:
        models._selected_models.clear()


def test_byok_stream_ignores_shared_model_effort_and_env(monkeypatch):
    from src.credentials import CredentialsMiddleware
    from src.selection import Selection, current_selection
    from src.model import request_model
    monkeypatch.setenv("LLM_MODEL", "claude-sonnet-5.5")
    monkeypatch.setenv("LLM_REASONING_EFFORT", "max")
    monkeypatch.setenv("AZURE_AI_FOUNDRY_ENABLED", "true")

    async def inner(scope, receive, send):
        assert current_selection.get() == Selection()
        model = request_model(None)
        assert model.model_name == "chat-latest"
        assert model.openai_api_base == "https://api.openai.com/v1"
        assert model.reasoning is None
        assert model.reasoning_effort is None
        assert model.use_responses_api is None
        assert model.openai_api_key.get_secret_value() == "visitor"
    async def noop(*args):
        pass
    scope = {"type": "http", "path": "/", "headers": [
        (b"x-ai-model", b"claude-sonnet-5.5"), (b"x-reasoning-effort", b"max"),
        (b"x-openai-api-key", b"visitor"), (b"x-jev-api-key", b"jev"),
    ]}
    asyncio.run(CredentialsMiddleware(inner)(scope, noop, noop))
    assert current_selection.get() == Selection()


def test_unavailable_explicit_selection_emits_fixed_run_error(monkeypatch, caplog):
    from ag_ui_langgraph import add_langgraph_fastapi_endpoint
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langgraph.graph import StateGraph, MessagesState, START, END
    from src.credentials import CredentialScopedAgent, CredentialsMiddleware
    from src.bounded_memory_saver import BoundedMemorySaver
    import src.model as models

    models._selected_models.clear()
    def fail(**kwargs):
        raise ValueError("private-provider-detail")
    monkeypatch.setattr(models, "build_model", fail)
    async def answer(state):
        models.request_model(None)
        return {"messages": []}
    builder = StateGraph(MessagesState)
    builder.add_node("answer", answer)
    builder.add_edge(START, "answer")
    builder.add_edge("answer", END)
    app = FastAPI()
    app.add_middleware(CredentialsMiddleware)
    # Avoid the server credential gate: the failure must originate in model selection.
    monkeypatch.setattr("src.credentials.server_credentials_available", lambda: True)
    add_langgraph_fastapi_endpoint(app, CredentialScopedAgent(
        name="test", graph=builder.compile(checkpointer=BoundedMemorySaver()),
    ))
    response = TestClient(app).post("/", headers={
        "x-ai-model": "claude-sonnet-5.5", "x-reasoning-effort": "max",
    }, json={
        "threadId": "thread", "runId": "run", "messages": [],
        "state": {}, "tools": [], "context": [], "forwardedProps": {},
    })
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]
    errors = [event for event in events if event["type"] == "RUN_ERROR"]
    assert len(errors) == 1
    assert errors[0]["code"] == "MODEL_SELECTION_UNAVAILABLE"
    assert "administrator" in errors[0]["message"]
    assert "private-provider-detail" not in response.text + caplog.text


def test_request_model_and_jev_override_without_environment_mutation(monkeypatch):
    from src.credentials import Credentials, current_credentials
    from src.model import request_model
    from src.visualization_router import request_options
    monkeypatch.setenv('AZURE_AI_FOUNDRY_ENABLED', 'false')
    monkeypatch.setenv('OPENAI_API_KEY', 'server-openai')
    monkeypatch.setenv('TYPESAFE_API_KEY', 'server-jev')
    monkeypatch.setenv('JEV_MODEL', 'server-model')
    token = current_credentials.set(Credentials('visitor-openai', 'visitor-jev'))
    try:
        model = request_model(None)
        assert model.model_name == 'chat-latest'
        assert model.openai_api_key.get_secret_value() == 'visitor-openai'
        assert request_options([])['headers']['Authorization'] == 'Bearer visitor-jev'
        assert request_options([])['json']['model'] == 'jev-latest'
        assert os.environ['OPENAI_API_KEY'] == 'server-openai'
    finally:
        current_credentials.reset(token)
    assert request_options([])['headers']['Authorization'] == 'Bearer server-jev'
    assert request_options([])['json']['model'] == 'server-model'
    sentinel = object()
    assert request_model(sentinel) is sentinel


def test_startup_without_credentials_uses_explicit_unconfigured_model(monkeypatch):
    from src.model import build_model
    monkeypatch.setenv('AZURE_AI_FOUNDRY_ENABLED', 'false')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('LLM_MODEL', raising=False)
    model = build_model(allow_unconfigured=True)
    with pytest.raises(ValueError, match='credentials'):
        model.invoke('hello')


def test_server_credentials_available_with_azure_foundry_default(monkeypatch):
    from src.credentials import server_credentials_available
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    monkeypatch.setenv('AZURE_AI_FOUNDRY_ENABLED', 'true')
    monkeypatch.setenv('LLM_MODEL', 'gpt-6-luna')
    assert server_credentials_available() is True

    monkeypatch.setenv('AZURE_AI_FOUNDRY_ENABLED', 'false')
    assert server_credentials_available() is False


def test_thread_namespace_separates_credentials_and_fallback():
    from src.credentials import Credentials, current_credentials, private_thread_id
    ids = []
    for creds in [None, Credentials('a', 'b'), Credentials('c', 'd')]:
        token = current_credentials.set(creds)
        try:
            first = private_thread_id('same-thread')
            assert first == private_thread_id('same-thread')
            ids.append(first)
        finally:
            current_credentials.reset(token)
    assert len(set(ids)) == 3
    assert all('same-thread' not in value for value in ids)


def test_validation_checks_both_providers_and_sanitizes_failure(monkeypatch):
    from src.credentials import Credentials, validate_credentials
    requests = []
    async def post(self, url, **kwargs):
        requests.append((url, kwargs))
        return httpx.Response(401, json={'error': 'SECRET visitor-openai'})
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    result = asyncio.run(validate_credentials(Credentials('visitor-openai', 'visitor-jev')))
    assert result.status_code == 401
    assert json.loads(result.body)['code'] == 'openai_invalid'
    assert 'SECRET' not in result.body.decode()
    assert len(requests) == 2


def test_agent_stream_keeps_credentials_out_of_checkpoints_and_separates_threads():
    from ag_ui.core import RunAgentInput
    from langchain_core.messages import AIMessage
    from langgraph.graph import StateGraph, MessagesState, START, END
    from src.bounded_memory_saver import BoundedMemorySaver
    from src.credentials import CredentialScopedAgent, Credentials, current_credentials

    seen = []
    async def answer(state):
        seen.append((current_credentials.get().openai, len(state['messages'])))
        return {'messages': [AIMessage(content='OK')]}
    builder = StateGraph(MessagesState)
    builder.add_node('answer', answer)
    builder.add_edge(START, 'answer')
    builder.add_edge('answer', END)
    saver = BoundedMemorySaver()
    adapter = CredentialScopedAgent(name='test', graph=builder.compile(checkpointer=saver))
    async def exercise():
        for index, key in enumerate(['visitor-first', 'visitor-second']):
            token = current_credentials.set(Credentials(key, 'visitor-jev'))
            try:
                input = RunAgentInput(thread_id='shared', run_id=f'run-{index}', messages=[{'id': f'message-{index}', 'role': 'user', 'content': 'Hello'}], state={}, tools=[], context=[], forwarded_props={})
                events = [event async for event in adapter.clone().run(input)]
                assert events
                assert all(event.thread_id == 'shared' for event in events if hasattr(event, 'thread_id'))
            finally:
                current_credentials.reset(token)
    asyncio.run(exercise())
    assert seen == [('visitor-first', 1), ('visitor-second', 1)]
    assert len(saver.storage) == 2
    persisted = repr((saver.storage, saver.writes, saver.blobs))
    # Message and run identifiers intentionally contain no credentials either.
    assert all(secret not in persisted for secret in ['visitor-first', 'visitor-second', 'visitor-jev'])


@pytest.mark.parametrize(
    ('status', 'code'),
    [(404, 'MODEL_DEPLOYMENT_NOT_FOUND'), (429, 'MODEL_RATE_LIMITED'), (500, 'MODEL_REQUEST_FAILED')],
)
def test_provider_failure_finishes_as_a_sanitized_sse_error(monkeypatch, caplog, status, code):
    import openai
    from ag_ui.core import EventType, RunStartedEvent
    from ag_ui_langgraph import add_langgraph_fastapi_endpoint
    from copilotkit import LangGraphAGUIAgent
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from langgraph.graph import StateGraph, MessagesState, START, END
    from src.credentials import CredentialScopedAgent

    async def fail(self, input):
        yield RunStartedEvent(type=EventType.RUN_STARTED, thread_id=input.thread_id, run_id=input.run_id)
        raise openai.APIStatusError(
            'upstream response contains visitor-secret',
            response=httpx.Response(status, request=httpx.Request('POST', 'https://provider.example')),
            body=None,
        )

    monkeypatch.setattr(LangGraphAGUIAgent, 'run', fail)
    builder = StateGraph(MessagesState)
    builder.add_edge(START, END)
    app = FastAPI()
    add_langgraph_fastapi_endpoint(app, CredentialScopedAgent(name='test', graph=builder.compile()))
    response = TestClient(app).post('/', json={
        'threadId': 'public-thread', 'runId': 'public-run', 'messages': [],
        'state': {}, 'tools': [], 'context': [], 'forwardedProps': {},
    })
    assert response.status_code == 200
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    assert [event['type'] for event in events] == ['RUN_STARTED', 'RUN_ERROR']
    assert events[0]['threadId'] == 'public-thread'
    assert events[-1]['code'] == code
    assert 'visitor-secret' not in response.text + caplog.text
    assert 'Agent provider request failed' in caplog.text


def test_main_starts_without_server_credentials(monkeypatch):
    import subprocess
    import sys
    environment = {k: v for k, v in os.environ.items() if k not in {'OPENAI_API_KEY', 'ANTHROPIC_API_KEY', 'TYPESAFE_API_KEY', 'LLM_MODEL'}}
    environment['PYTHON_DOTENV_DISABLED'] = '1'
    environment['AZURE_AI_FOUNDRY_ENABLED'] = 'false'
    result = subprocess.run([sys.executable, '-c', "from fastapi.testclient import TestClient; from main import app; c=TestClient(app); assert c.get('/health').status_code == 200; r=c.post('/', json={}); assert r.status_code == 401; assert r.json()['code'] == 'credentials_required'"], env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(('statuses', 'code'), [([200, 200], None), ([200, 403], 'jev_invalid'), ([429, 200], 'provider_unavailable')])
def test_validation_endpoint_results(monkeypatch, statuses, code):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.credentials import CredentialsMiddleware, current_credentials, validate_credentials
    app = FastAPI()
    app.add_middleware(CredentialsMiddleware)
    @app.post('/credentials/validate')
    async def validate():
        return await validate_credentials(current_credentials.get())
    async def post(self, url, **kwargs):
        return httpx.Response(statuses[0 if 'openai' in url else 1])
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    response = TestClient(app).post('/credentials/validate', headers={'x-openai-api-key': 'openai', 'x-jev-api-key': 'jev'})
    assert response.json() == ({'ok': False, 'code': code} if code else {'ok': True})


def test_actual_stream_disconnect_retains_then_releases_context():
    from starlette.responses import StreamingResponse
    from src.credentials import CredentialsMiddleware, current_credentials
    async def exercise():
        first_chunk = asyncio.Event()
        finalized = asyncio.Event()
        observed = []
        async def chunks():
            try:
                observed.append(current_credentials.get().openai)
                yield b'first'
                await asyncio.Event().wait()
            finally:
                observed.append(current_credentials.get().openai)
                finalized.set()
        async def inner(scope, receive, send):
            await StreamingResponse(chunks())(scope, receive, send)
        async def receive():
            await first_chunk.wait()
            return {'type': 'http.disconnect'}
        async def send(message):
            if message['type'] == 'http.response.body':
                first_chunk.set()
        scope = {'type': 'http', 'path': '/', 'asgi': {'spec_version': '2.0'}, 'headers': [(b'x-openai-api-key', b'visitor'), (b'x-jev-api-key', b'jev')]}
        await CredentialsMiddleware(inner)(scope, receive, send)
        assert finalized.is_set()
        assert observed == ['visitor', 'visitor']
        assert current_credentials.get() is None
    asyncio.run(exercise())


def test_shared_stream_disconnect_retains_then_releases_selection():
    from starlette.responses import StreamingResponse
    from src.credentials import CredentialsMiddleware
    from src.selection import Selection, current_selection
    async def exercise():
        first_chunk = asyncio.Event()
        observed = []
        expected = Selection("gpt-6-luna", reasoning_effort="max")
        async def chunks():
            try:
                observed.append(current_selection.get())
                yield b"first"
                await asyncio.Event().wait()
            finally:
                observed.append(current_selection.get())
        async def inner(scope, receive, send):
            await StreamingResponse(chunks())(scope, receive, send)
        async def receive():
            await first_chunk.wait()
            return {"type": "http.disconnect"}
        async def send(message):
            if message["type"] == "http.response.body":
                first_chunk.set()
        scope = {"type": "http", "path": "/stream", "asgi": {"spec_version": "2.0"}, "headers": [
            (b"x-ai-model", b"gpt-6-luna"), (b"x-reasoning-effort", b"max"),
        ]}
        await CredentialsMiddleware(inner)(scope, receive, send)
        assert observed == [expected, expected]
        assert current_selection.get() == Selection()
    asyncio.run(exercise())


def test_internal_model_calls_also_use_request_credentials(monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    import src.model as models
    assert hasattr(models, 'CredentialScopedModel')
    fallback = FakeMessagesListChatModel(responses=[AIMessage(content='server')])
    visitor = FakeMessagesListChatModel(responses=[AIMessage(content='visitor')])
    monkeypatch.setattr(models, 'request_model', lambda ignored: visitor)
    wrapped = models.CredentialScopedModel(fallback=fallback)
    assert wrapped.invoke('summary').content == 'visitor'
    assert asyncio.run(wrapped.ainvoke('summary')).content == 'visitor'


def test_internal_provider_errors_do_not_expose_upstream_content(monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage
    from src.credentials import Credentials, current_credentials
    import src.model as models
    class FailingModel(FakeMessagesListChatModel):
        def _generate(self, *args, **kwargs):
            raise ValueError('upstream includes visitor-secret')
    failing = FailingModel(responses=[AIMessage(content='unused')])
    monkeypatch.setattr(models, 'request_model', lambda ignored: failing)
    token = current_credentials.set(Credentials('visitor-secret', 'jev'))
    try:
        with pytest.raises(ValueError) as error:
            models.CredentialScopedModel(fallback=failing).invoke('summary')
        assert 'visitor-secret' not in str(error.value)
    finally:
        current_credentials.reset(token)


def test_internal_streaming_errors_are_sanitized(monkeypatch):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessage, AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk
    from src.credentials import Credentials, current_credentials
    import src.model as models
    class FailingStream(FakeMessagesListChatModel):
        def _stream(self, *args, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content='first'))
            raise ValueError('upstream includes visitor-secret')
    failing = FailingStream(responses=[AIMessage(content='unused')])
    monkeypatch.setattr(models, 'request_model', lambda ignored: failing)
    async def exercise():
        token = current_credentials.set(Credentials('visitor-secret', 'jev'))
        try:
            wrapped = models.CredentialScopedModel(fallback=failing)
            with pytest.raises(ValueError) as error:
                [chunk async for chunk in wrapped.astream('summary')]
            assert 'visitor-secret' not in str(error.value)
        finally:
            current_credentials.reset(token)
    asyncio.run(exercise())


def test_credential_scoped_model_does_not_duplicate_stream_events():
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk
    import src.model as models

    class ToolStreamModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self.bind(tools=tools, **kwargs)

        async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
            assert 'tools' in kwargs
            for delta in ['{"a":', '1,', '"b":2}']:
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content='',
                        tool_call_chunks=[
                            {
                                'name': 'my_tool',
                                'args': delta,
                                'id': 'call_1',
                                'index': 0,
                                'type': 'tool_call_chunk',
                            }
                        ],
                    )
                )

    async def exercise():
        wrapped = models.CredentialScopedModel(fallback=ToolStreamModel(responses=[]))
        bound = wrapped.bind_tools([{'type': 'function', 'function': {'name': 'my_tool', 'parameters': {'type': 'object', 'properties': {}}}}])
        events = [
            ev
            async for ev in bound.astream_events('hi', version='v2')
            if ev['event'] == 'on_chat_model_stream'
            and ev['data']['chunk'].tool_call_chunks
        ]
        combined = ''.join(ev['data']['chunk'].tool_call_chunks[0]['args'] for ev in events)
        assert json.loads(combined) == {'a': 1, 'b': 2}

    asyncio.run(exercise())


def test_byok_clients_ignore_server_openai_environment(monkeypatch):
    from src.credentials import Credentials, current_credentials
    from src.model import request_model
    poison = {
        'OPENAI_CUSTOM_HEADERS': 'Authorization: Bearer host-key\nOpenAI-Organization: host-org\nX-Host-Secret: host-secret',
        'OPENAI_ADMIN_KEY': 'host-admin',
        'OPENAI_WEBHOOK_SECRET': 'host-webhook',
        'OPENAI_ORG_ID': 'server-org',
        'OPENAI_ORGANIZATION': 'server-organization',
        'OPENAI_PROJECT_ID': 'server-project',
        'OPENAI_PROXY': 'http://127.0.0.1:9999',
        'OPENAI_BASE_URL': 'http://127.0.0.1:9998',
        'HTTPS_PROXY': 'http://127.0.0.1:9997',
    }
    for name, value in poison.items():
        monkeypatch.setenv(name, value)
    token = current_credentials.set(Credentials('visitor-key', 'visitor-jev'))
    try:
        model = request_model(None)
        for client in [model.root_client, model.root_async_client]:
            assert client.organization is None
            assert client.project is None
            assert str(client.base_url) == 'https://api.openai.com/v1/'
            assert client.api_key == 'visitor-key'
            assert not client._client.trust_env
            assert 'X-Host-Secret' not in client.default_headers
            assert client.admin_api_key is None
            assert client.webhook_secret is None
        sent = []
        def send(client, request, **kwargs):
            sent.append(request)
            return httpx.Response(200, request=request, json={
                'id': 'test', 'object': 'chat.completion', 'created': 0,
                'model': 'chat-latest', 'choices': [],
            })
        async def asend(client, request, **kwargs):
            return send(client, request, **kwargs)
        monkeypatch.setattr(httpx.Client, 'send', send)
        monkeypatch.setattr(httpx.AsyncClient, 'send', asend)
        model.root_client.chat.completions.create(model='chat-latest', messages=[])
        asyncio.run(model.root_async_client.chat.completions.create(model='chat-latest', messages=[]))
        assert len(sent) == 2
        for request in sent:
            assert request.headers['Authorization'] == 'Bearer visitor-key'
            assert 'OpenAI-Organization' not in request.headers
            assert 'OpenAI-Project' not in request.headers
            assert 'X-Host-Secret' not in request.headers
        assert not model.openai_proxy
        assert all(os.environ[name] == value for name, value in poison.items())
    finally:
        current_credentials.reset(token)


def test_byok_validation_and_jev_ignore_proxy_environment(monkeypatch):
    import src.visualization_router as router
    from src.credentials import Credentials, current_credentials, validate_credentials
    from src.visualization_router import route, aroute
    observed = []
    def post(self, url, **kwargs):
        observed.append(self.trust_env)
        return httpx.Response(503)
    async def apost(self, url, **kwargs):
        return post(self, url, **kwargs)
    async def no_async_sleep(_delay):
        pass
    monkeypatch.setattr(httpx.Client, 'post', post)
    monkeypatch.setattr(httpx.AsyncClient, 'post', apost)
    monkeypatch.setattr(router.time, 'sleep', lambda _delay: None)
    monkeypatch.setattr(router.asyncio, 'sleep', no_async_sleep)
    creds = Credentials('visitor', 'jev')
    asyncio.run(validate_credentials(creds))
    token = current_credentials.set(creds)
    try:
        with pytest.raises(ValueError):
            route([])
        with pytest.raises(ValueError):
            asyncio.run(aroute([]))
    finally:
        current_credentials.reset(token)
    assert observed == [False] * 10
