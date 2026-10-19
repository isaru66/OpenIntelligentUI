# Deployment

This guide describes how to deploy Open Generative UI; it does not establish that a release is deployed. Keep existing service names and URLs intact when changing visible product branding.

## Azure Container Apps

The [Azure infrastructure guide](../infra/README.md) describes the Terraform/azd
deployment: public HTTPS web app, internal HTTPS agent, ACR remote builds owned by
Terraform, and a new Foundry account/project with chat and Decision deployments.
The agent uses managed identity for Foundry and an ACA secret for the existing
WebIQ API key. Application source is unchanged. This is a provision-only azd
project: use `azd provision` or `azd up`, not `azd deploy`.

Subscription, application/Foundry regions, and the exact chat model version are
deployment inputs. The initial workflow uses local state, which contains the
WebIQ key and must be protected. Follow the infrastructure guide's WSL setup,
secret-handling precautions, and live acceptance steps before calling it a
deployed release.

## Render blueprint

The repository's `render.yaml` defines two services:

| Service                    | Runtime and root            | Build                                                                                                  | Start / health                                                   |
| -------------------------- | --------------------------- | ------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| `open-generative-ui-agent` | Python 3.12.6, `apps/agent` | `pip install uv && uv sync`                                                                            | `uv run uvicorn main:app --host 0.0.0.0 --port $PORT`, `/health` |
| `open-generative-ui-app`   | Node 22, repository root    | `corepack enable && pnpm install --no-frozen-lockfile && pnpm exec turbo run build --filter=@repo/app` | `pnpm --filter @repo/app start`, `/api/health`                   |

By default in local development, the Python factory uses Azure AI Foundry (`AZURE_AI_FOUNDRY_ENDPOINT=https://ai-isarar-2855.services.ai.azure.com`) with Entra ID authentication (`AZURE_SUBSCRIPTION_ID`, `AZURE_TENANT_ID`), `LLM_MODEL=gpt-6-luna`, and `AZURE_DECISION_DEPLOYMENT=Decision-1` (`Microsoft-Decision-1`) for visualization routing, plus Microsoft Web IQ (`WEBIQ_API_KEY`, `WEBIQ_ENDPOINT`) for public internet grounding. When `AZURE_AI_FOUNDRY_ENABLED=false` (or in the Render blueprint), the agent can use `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` and `TYPESAFE_API_KEY`. Verify access to the selected model before launch; a configured model name does not prove availability.

| Variable                                  | Service       | Purpose                                                                             |
| ----------------------------------------- | ------------- | ----------------------------------------------------------------------------------- |
| `AZURE_AI_FOUNDRY_ENABLED`                | Agent         | Defaults to `true` for Entra ID authentication against Azure AI Foundry             |
| `AZURE_AI_FOUNDRY_ENDPOINT`               | Agent         | Azure AI Foundry base endpoint (`https://ai-isarar-2855.services.ai.azure.com`)     |
| `AZURE_SUBSCRIPTION_ID`                   | Agent         | Azure subscription ID for CLI/Entra credential resolution                           |
| `AZURE_TENANT_ID`                         | Agent         | Azure Entra tenant ID (`ddcbdc96-6162-4d91-bb0d-066343049ce1`)                      |
| `LLM_MODEL`                               | Agent         | Defaults to `gpt-6-luna` on Foundry; `claude-*` routes to Anthropic. The prompt-box AI model choices `gpt-6-luna` and `gpt-6.1-sol` are Foundry deployments on the same resource (deployment name = model name) |
| `AZURE_DECISION_DEPLOYMENT`               | Agent         | Foundry SystemOne deployment name (defaults to `Decision-1`)                        |
| `WEBIQ_API_KEY`                           | Agent         | API key (`x-apikey`) for Microsoft Web IQ public internet grounding                 |
| `WEBIQ_ENDPOINT`                          | Agent         | Web IQ endpoint URL (defaults to `https://api.microsoft.ai/v3/search/web`)          |
| `ANTHROPIC_API_KEY`                       | Agent         | Required when selecting Anthropic (`claude-*`)                                      |
| `OPENAI_API_KEY`                          | Agent         | Required when selecting OpenAI with `AZURE_AI_FOUNDRY_ENABLED=false`                |
| `TYPESAFE_API_KEY`                        | Agent         | Required for Jev routing when `AZURE_AI_FOUNDRY_ENABLED=false`                      |
| `LANGSMITH_API_KEY`                       | As configured | Optional tracing configuration                                                      |
| `LANGGRAPH_DEPLOYMENT_URL`                | Frontend      | Blueprint obtains agent host:port via `fromService`; runtime normalizes it to a URL |
| `RATE_LIMIT_ENABLED`                      | Frontend      | Defaults to `false` in blueprint                                                    |
| `RATE_LIMIT_WINDOW_MS` / `RATE_LIMIT_MAX` | Frontend      | Request-limit configuration                                                         |
| `MCP_SERVER_URL`                          | Frontend      | Optional MCP integration                                                            |

The agent rejects blank or unsupported model names at startup. Missing shared provider keys allow a BYOK-only deployment; requests without visitor keys receive a credentials-required response. Never put provider keys in public frontend variables.

To deploy, connect your repository to a Render Blueprint, review its explicit model setting, supply the corresponding provider secret, and deploy the reviewed revision. The blueprint links the frontend to the agent; verify the resulting connection with an actual prompt.

Both services declare scaling from one to three instances. Agent checkpoints currently live in bounded process memory, and the frontend rate limiter is process-local. Scaling or restarting can lose/split conversation state and changes effective rate-limit behavior. Durable shared state and coordinated limits require additional infrastructure.

## Visitor API keys

Visitors can supply OpenAI and Jev keys through **API keys** in the chat header. The Next.js runtime forwards only `x-openai-api-key` and `x-jev-api-key` to the configured agent, creating a separate runtime instance per request. The Python ASGI middleware strips these headers before the inner application and scopes credentials to the entire streaming request without changing process environment variables. BYOK conversations have credential-specific checkpoint IDs, separate from shared-mode conversations. Both keys are required; partial pairs never fall back to server secrets.

`POST /api/provider-keys` proxies connection validation to the agent’s `POST /credentials/validate`. It performs small real provider requests and returns only fixed error messages. BYOK always uses the standard OpenAI endpoint and `chat-latest`; Jev uses `jev-latest`. Hosted LangSmith tracing is disabled for BYOK. The application does not persist the keys, but its server necessarily receives them: use HTTPS externally and a trusted private or TLS connection between frontend and agent. Do not configure infrastructure to log credential headers.

## Other hosts

Run the agent:

```bash
cd apps/agent
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8123
```

Supply the provider key and optional `LLM_MODEL` in that service's environment. Run the frontend from the repository root:

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm exec turbo run build --filter=@repo/app
LANGGRAPH_DEPLOYMENT_URL=http://your-agent-host:8123 pnpm --filter @repo/app start
```

Use a reachable agent URL appropriate to your network. Expose the frontend through your host's normal HTTPS routing. The optional MCP server is a separate deployment; see its [guide](../apps/mcp/README.md). A frontend Dockerfile is available at `docker/Dockerfile.app`.

## Verification and launch

1. Review the exact revision and provider configuration. Keep service identifiers stable and ensure secrets remain server-side.
2. Run the automated checks from the repository root:

   ```bash
   pnpm test
   uv run --directory apps/agent pytest
   pnpm lint
   pnpm build
   ```

   Turbo builds shared dependencies for workspace checks. For isolated MCP tests, build `@repo/design-system` first.

3. Check the chat layout at desktop and narrow widths. Exercise the composer, starter suggestions, and New chat. For generated tools, check keyboard controls, visible focus, numerical boundaries, and reset behavior.
4. Make real provider-backed requests for a direct text answer, an explainer, a comparison, and a working calculator. Verify streaming reaches the interactive final sandbox. Confirm current-data requests do not fabricate evidence.
5. Exercise a user-clicked follow-up with selected values. Confirm it starts a new turn/output, preserves earlier artifacts, and reports relevant errors. Check that ordinary controls do not send prompts.
6. Check analytics before launch: set `OIUI_DISTRIBUTION` and `NEXT_PUBLIC_POSTHOG_KEY` on the frontend, then confirm a page view and the two install events arrive in PostHog (see [Telemetry](telemetry.md)).
7. Deploy the reviewed revision. Confirm both health endpoints return `{"status":"ok"}`, then repeat a real prompt against the deployed frontend. Health checks alone do not test provider authentication, streaming, or browser behavior.
8. Record the deployed revision, environment, checks actually performed, and remaining limitations. If validation fails, use the host's rollback workflow to restore a known working revision.

A rendered chat interface alone is not a model smoke test; verify a real response. Do not describe local test success as a deployed launch. See [Getting started](getting-started.md) and [Architecture](architecture.md) for setup and runtime details.

Set `APP_URL` on the frontend to the public custom-domain origin when using one. Social image metadata uses this value, then `RENDER_EXTERNAL_URL`, then the existing demo hostname.
