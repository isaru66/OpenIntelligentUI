"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAgent } from "@copilotkit/react-core/v2";

export const AI_MODELS = ["gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5.5"] as const;
export const DECISION_MODELS = ["Microsoft-Decision-1", "Jev"] as const;
export type AiModel = (typeof AI_MODELS)[number];
export type DecisionModel = (typeof DECISION_MODELS)[number];
export type ModelSnapshot = { aiModel: AiModel; decisionModel: DecisionModel };

export const DEFAULT_AI_MODEL: AiModel = "gpt-6-luna";
export const DEFAULT_DECISION_MODEL: DecisionModel = "Microsoft-Decision-1";
export const MODEL_STORAGE_KEY = "open-intelligent-ui:model-selection";

type ModelSelectionValue = ModelSnapshot & {
  setAiModel: (value: AiModel) => void;
  setDecisionModel: (value: DecisionModel) => void;
  headers: Record<string, string>;
  attributions: Record<string, ModelSnapshot>;
  /** Freeze the current selection for the run that is starting. */
  beginRun: () => void;
  /** Attach the frozen run selection to a message, once. */
  attribute: (messageId: string) => void;
};

const defaults: ModelSelectionValue = {
  aiModel: DEFAULT_AI_MODEL,
  decisionModel: DEFAULT_DECISION_MODEL,
  setAiModel: () => {},
  setDecisionModel: () => {},
  headers: { "x-ai-model": DEFAULT_AI_MODEL, "x-decision-model": DEFAULT_DECISION_MODEL },
  attributions: {},
  beginRun: () => {},
  attribute: () => {},
};
const ModelSelectionContext = createContext<ModelSelectionValue>(defaults);

const pick = <T extends string>(options: readonly T[], value: unknown): T | undefined =>
  options.find((option) => option === value);

export function ModelSelectionProvider({ children }: { children: ReactNode }) {
  const [aiModel, setAi] = useState<AiModel>(DEFAULT_AI_MODEL);
  const [decisionModel, setDecision] = useState<DecisionModel>(DEFAULT_DECISION_MODEL);
  const [attributions, setAttributions] = useState<Record<string, ModelSnapshot>>({});
  const current = useRef<ModelSnapshot | null>(null);
  const runSnapshot = useRef<ModelSnapshot | null>(null);
  const loaded = useRef(false);
  useEffect(() => { current.current = { aiModel, decisionModel }; }, [aiModel, decisionModel]);
  const beginRun = useCallback(() => { runSnapshot.current = current.current; }, []);
  const attribute = useCallback((id: string) => {
    const snapshot = runSnapshot.current ?? current.current;
    if (snapshot) setAttributions((existing) => existing[id] ? existing : { ...existing, [id]: snapshot });
  }, []);

  // Read storage after mount so server and first client render agree.
  useEffect(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem(MODEL_STORAGE_KEY) ?? "{}");
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setAi(pick(AI_MODELS, stored?.aiModel) ?? DEFAULT_AI_MODEL);
      setDecision(pick(DECISION_MODELS, stored?.decisionModel) ?? DEFAULT_DECISION_MODEL);
    } catch {}
    loaded.current = true;
  }, []);
  useEffect(() => {
    if (!loaded.current) return;
    try {
      window.localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify({ aiModel, decisionModel }));
    } catch {}
  }, [aiModel, decisionModel]);

  const value = useMemo<ModelSelectionValue>(() => ({
    aiModel,
    decisionModel,
    setAiModel: setAi,
    setDecisionModel: setDecision,
    headers: { "x-ai-model": aiModel, "x-decision-model": decisionModel },
    attributions,
    beginRun,
    attribute,
  }), [aiModel, decisionModel, attributions, beginRun, attribute]);

  return <ModelSelectionContext.Provider value={value}>{children}</ModelSelectionContext.Provider>;
}

export function useModelSelection() {
  return useContext(ModelSelectionContext);
}

/** Records which models each assistant message was produced with, so later dropdown changes never rewrite history. */
export function ModelAttributionRecorder() {
  const { agent } = useAgent();
  const { beginRun, attribute } = useModelSelection();
  useEffect(() => {
    const subscription = agent.subscribe({
      onRunInitialized: () => { beginRun(); },
      onNewMessage: ({ message }) => { if (message.role === "assistant") attribute(message.id); },
    });
    return () => subscription.unsubscribe();
  }, [agent, beginRun, attribute]);
  return null;
}
