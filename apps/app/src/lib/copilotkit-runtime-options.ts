import { LangGraphHttpAgent } from "@copilotkit/runtime/langgraph";

import type { ModelHeaders } from "./model-headers";
import type { ProviderHeaders } from "./provider-keys";

class CredentialSafeLangGraphAgent extends LangGraphHttpAgent {
  protected override requestInit(input: Parameters<LangGraphHttpAgent["requestInit"]>[0]): RequestInit {
    // Custom credential headers survive cross-origin fetch redirects. Fail closed.
    return { ...super.requestInit(input), redirect: "error" };
  }
}

export interface RuntimeOptionsEnv {
  langgraphUrl?: string;
  mcpServerUrl?: string;
  providerHeaders?: ProviderHeaders;
  modelHeaders?: ModelHeaders;
}

// Normalize Render's fromService hostport (bare host:port) into a full URL
export function normalizeLanggraphUrl(raw?: string): string {
  if (!raw) return "http://localhost:8123";
  return raw.startsWith("http") ? raw : `http://${raw}`;
}

export function buildRuntimeOptions(env: RuntimeOptionsEnv) {
  return {
    agents: {
      default: new CredentialSafeLangGraphAgent({
        url: normalizeLanggraphUrl(env.langgraphUrl),
        ...((env.providerHeaders || (env.modelHeaders && Object.keys(env.modelHeaders).length > 0)) && {
          headers: { ...env.modelHeaders, ...env.providerHeaders },
        }),
      }),
    },
    a2ui: { injectA2UITool: true },
    openGenerativeUI: true as const,
    ...(env.mcpServerUrl && {
      mcpApps: {
        servers: [{
          type: "http" as const,
          url: env.mcpServerUrl,
          serverId: "example_mcp_app",
        }],
      },
    }),
  };
}
