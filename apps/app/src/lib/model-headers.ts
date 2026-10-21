export const AI_MODELS = ["gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5.5"] as const;
export const DECISION_MODELS = ["Microsoft-Decision-1", "Jev"] as const;
export type AiModel = (typeof AI_MODELS)[number];
export type DecisionModel = (typeof DECISION_MODELS)[number];
export const REASONING_EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"] as const;
export type ReasoningEffort = (typeof REASONING_EFFORTS)[number];
export const DEFAULT_REASONING_EFFORT: ReasoningEffort = "medium";
export const EFFORT_LABELS: Record<ReasoningEffort, string> = {
  none: "None", low: "Low", medium: "Medium", high: "High", xhigh: "Extra High", max: "Max",
};
export const MODEL_EFFORTS: Record<AiModel, readonly ReasoningEffort[]> = {
  "gpt-6-luna": REASONING_EFFORTS,
  "gpt-6.1-sol": REASONING_EFFORTS.filter((effort) => effort !== "none"),
  "claude-sonnet-5.5": REASONING_EFFORTS.filter((effort) => effort !== "none"),
};

export function normalizeEffort(model: AiModel, value: unknown): ReasoningEffort {
  return MODEL_EFFORTS[model].find((effort) => effort === value) ?? DEFAULT_REASONING_EFFORT;
}

export type ModelHeaders = { "x-ai-model"?: string; "x-decision-model"?: string; "x-reasoning-effort"?: string };

// Unknown values are dropped so the agent applies its own default.
export function readModelHeaders(headers: Headers): ModelHeaders {
  const ai = headers.get("x-ai-model")?.trim();
  const decision = headers.get("x-decision-model")?.trim();
  const model = AI_MODELS.find((model) => model === ai);
  return {
    ...(model && { "x-ai-model": model, "x-reasoning-effort": normalizeEffort(model, headers.get("x-reasoning-effort")?.trim()) }),
    ...(decision && (DECISION_MODELS as readonly string[]).includes(decision) && { "x-decision-model": decision }),
  };
}