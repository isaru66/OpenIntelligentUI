export const AI_MODELS = ["gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5.5"] as const;
export const DECISION_MODELS = ["Microsoft-Decision-1", "Jev"] as const;

export type ModelHeaders = { "x-ai-model"?: string; "x-decision-model"?: string };

// Unknown values are dropped so the agent applies its own default.
export function readModelHeaders(headers: Headers): ModelHeaders {
  const ai = headers.get("x-ai-model")?.trim();
  const decision = headers.get("x-decision-model")?.trim();
  return {
    ...(ai && (AI_MODELS as readonly string[]).includes(ai) && { "x-ai-model": ai }),
    ...(decision && (DECISION_MODELS as readonly string[]).includes(decision) && { "x-decision-model": decision }),
  };
}