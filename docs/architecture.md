# Architecture

Open Generative UI combines a Python agent with a CopilotKit runtime and a browser renderer. The `openGenerativeUI` runtime API and `generateSandboxedUi` tool connect them.

## Components

| Location                  | Responsibility                                            |
| ------------------------- | --------------------------------------------------------- |
| `apps/app/`               | Next.js frontend and `/api/copilotkit` runtime route      |
| `apps/agent/`             | FastAPI, LangGraph, Deep Agent, tools, prompt, and skills |
| `apps/mcp/`               | Optional standalone MCP resources and HTML assembler      |
| `packages/design-system/` | Shared theme, SVG classes, and form styles                |

Node packages use pnpm/Turborepo. The Python agent uses uv.

## Request flow

```text
User prompt or chat starter suggestion
  → CopilotKit chat / agent run
  → Next.js /api/copilotkit
  → LangGraphHttpAgent → FastAPI agent
  → model + applicable tools and skills
  → text, native component, or generateSandboxedUi
  → CopilotKit activity stream → browser renderer
```

The agent uses `create_deep_agent`, CopilotKit middleware, an Anthropic compatibility middleware, and `BoundedMemorySaver(max_threads=200)`. The checkpoint store is process memory, not durable shared storage. Restarting or scaling the agent can lose or split conversation state.

`src/model.py` defaults to `LLM_MODEL=gpt-6-luna` on Azure AI Foundry (`AZURE_AI_FOUNDRY_ENDPOINT`, default `https://ai-isarar-2855.services.ai.azure.com`) using Entra ID token authentication via `src/azure_auth.py` (`AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`, scope `https://cognitiveservices.azure.com/.default`). Before each user turn, `src/visualization_router.py` routes visualization decisions through `Microsoft-Decision-1` (`AZURE_DECISION_DEPLOYMENT=Decision-1`) at `/providers/microsoft/v1/systemone` using the same Entra ID bearer token. When `AZURE_AI_FOUNDRY_ENABLED=false` or `claude-*` is selected, `src/model.py` and `src/visualization_router.py` use direct provider credentials (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `TYPESAFE_API_KEY`).

### Per-turn model and effort

In shared mode, the AI picker offers `gpt-6-luna`, `gpt-6.1-sol`, and `claude-sonnet-5.5`. Clicking a model name selects it at **Medium** effort. Its separate chevron previews an effort submenu without changing the selection; choosing an effort applies both together. The current selection persists locally across reloads. On narrow screens, the submenu replaces the model panel and provides a Back control.

All three models offer Low, Medium, High, Extra High (`xhigh`), and Max; only GPT-6 Luna offers None. The frontend validates the model/effort pair and forwards `x-ai-model`, `x-reasoning-effort`, and `x-decision-model` through the per-request runtime. Python validates them again and holds the selection in a ContextVar for the complete stream. A valid selected model with missing or invalid effort uses Medium. Without a valid selected model, the existing server configuration applies.

GPT choices use the Responses API with `reasoning.effort`; Claude uses `output_config.effort` with adaptive thinking. Explicit picker effort takes precedence over the server's environment setting. Cached model instances are separated by model and effort; changing effort does not mutate another run's instance. Unavailable explicit selections produce an actionable run error rather than silently using a different model. Reply chips retain the selection frozen when their run began.

BYOK remains fixed to OpenAI `chat-latest` and Jev. Its controls are disabled with an explanation, shared-mode overrides are omitted, and reply chips do not claim an unsupported effort. Clearing visitor keys restores the saved shared-mode selection.

`src/webiq.py` provides the `web_search` tool for live public internet grounding via Microsoft Web IQ (`POST https://api.microsoft.ai/v3/search/web`, configurable with `WEBIQ_ENDPOINT` and authenticated via `WEBIQ_API_KEY`). 

`src/prompt.py` and the three agent skills guide response selection. Plain text is appropriate for direct answers. Native components handle supported structured tasks; custom UI serves useful diagrams, comparisons, calculators, and simulations. Planning is optional. See [Product and agent behavior](interactive-answers.md).

## Streaming custom UI

The runtime enables `openGenerativeUI`; its middleware translates `generateSandboxedUi` into `open-generative-ui` activity messages. The tool's ordered fields are:

1. `initialHeight`
2. `placeholderMessages`
3. `css`
4. `html`
5. `jsFunctions`
6. `jsExpressions`

The renderer holds the placeholder until CSS is complete, progressively updates a preview iframe, then initializes the final Websandbox iframe. Shared theme CSS and a CDN importmap are injected. JavaScript function/expression channels execute as classic scripts, so top-level await is invalid; asynchronous imports belong inside async functions.

The sandbox has no same-origin access to storage or host APIs. The host exposes validated `sendPrompt({ text })` and HTTPS `openLink({ url })` callbacks through `Websandbox.connection.remote`. Resize messages are checked and bounded before setting iframe height. Keep these boundaries intact when modifying the renderer.

A follow-up starts a new agent turn. Prior generated outputs serve as separate snapshots of that answer; their local controls can still change their own UI. There is no supported cross-call DOM patch API, and arbitrary iframe control state is not automatically synchronized to the agent. Follow-up buttons should include relevant selected values explicitly.

## Chat and evidence

The page always displays CopilotChat, with three task-oriented starter suggestions. User prompts run the shared agent; answers and interactive components appear in that conversation. New chat starts a fresh thread. `query_data` returns an envelope with source metadata and all bundled sample CSV rows; its natural-language query is not applied. Neither a renderer nor a native card establishes a live data connection.

Legacy todo tools remain in the agent and can manipulate their supported state; the login-form schema is a nonfunctional demonstration. They do not define the main product experience.

## Standalone MCP

The MCP server exposes skills, prompts, and `assemble_document`. The assembler returns HTML text with shared styles and legacy postMessage helpers. A consuming host must render the document in isolation and validate bridge requests. This server does not supply the web app's Websandbox bridge or importmap, and assembling a document does not display or deploy it.

## Key implementation files

- Agent: `apps/agent/main.py`, `src/azure_auth.py`, `src/model.py`, `src/visualization_router.py`, `src/webiq.py`, `src/prompt.py`, `src/query.py`, `skills/`.
- Runtime: `apps/app/src/app/api/copilotkit/route.ts`, `src/lib/copilotkit-runtime-options.ts`.
- Renderer: `apps/app/src/components/generative-ui/open-generative-ui/`.
- Host bridge: `apps/app/src/lib/sandbox/`.
- MCP assembly: `apps/mcp/src/server.ts`, `src/renderer.ts`.

See [Deployment](deployment.md) for runtime configuration and operational limits.
