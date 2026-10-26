"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useAgent } from "@copilotkit/react-core/v2";
import { AI_MODELS, DECISION_MODELS, DEFAULT_REASONING_EFFORT, normalizeEffort, type AiModel, type DecisionModel, type ReasoningEffort } from "@/lib/model-headers";

export { AI_MODELS, DECISION_MODELS };
export type { AiModel, DecisionModel };
export type ModelSnapshot = { aiModel: AiModel; decisionModel: DecisionModel; reasoningEffort: ReasoningEffort };
type RunSnapshot = ModelSnapshot | { aiModel: "chat-latest"; decisionModel: "Jev"; reasoningEffort?: never };

export const DEFAULT_AI_MODEL: AiModel = "gpt-6-luna";
export const DEFAULT_DECISION_MODEL: DecisionModel = "Microsoft-Decision-1";
export const MODEL_STORAGE_KEY = "open-intelligent-ui:model-selection";
const initial: ModelSnapshot = { aiModel: DEFAULT_AI_MODEL, decisionModel: DEFAULT_DECISION_MODEL, reasoningEffort: DEFAULT_REASONING_EFFORT };
const noHeaders: Record<string, string> = {};

type ModelSelectionValue = ModelSnapshot & {
  setAiModel: (value: AiModel) => void;
  setModelEffort: (model: AiModel, effort: ReasoningEffort) => void;
  setDecisionModel: (value: DecisionModel) => void;
  headers: Record<string, string>;
  attributions: Record<string, RunSnapshot>;
  beginRun: () => void;
  attribute: (messageId: string) => void;
};

const ModelSelectionContext = createContext<ModelSelectionValue>({
  ...initial,
  setAiModel: () => {}, setModelEffort: () => {}, setDecisionModel: () => {},
  headers: { "x-ai-model": initial.aiModel, "x-decision-model": initial.decisionModel, "x-reasoning-effort": initial.reasoningEffort },
  attributions: {}, beginRun: () => {}, attribute: () => {},
});

export function ModelSelectionProvider({ children, byok = false }: { children: ReactNode; byok?: boolean }) {
  const [selection, setSelection] = useState<ModelSnapshot>(initial);
  const [loaded, setLoaded] = useState(false);
  const [attributions, setAttributions] = useState<Record<string, RunSnapshot>>({});
  const current = useRef<RunSnapshot>(initial);
  const runSnapshot = useRef<RunSnapshot | null>(null);
  useEffect(() => {
    current.current = byok ? { aiModel: "chat-latest", decisionModel: "Jev" } : selection;
  }, [selection, byok]);
  const beginRun = useCallback(() => { runSnapshot.current = current.current; }, []);
  const attribute = useCallback((id: string) => {
    const snapshot = runSnapshot.current ?? current.current;
    setAttributions((existing) => existing[id] ? existing : { ...existing, [id]: snapshot });
  }, []);

  useEffect(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem(MODEL_STORAGE_KEY) ?? "{}");
      const storedModel = AI_MODELS.find((model) => model === stored?.aiModel);
      const aiModel = storedModel ?? DEFAULT_AI_MODEL;
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelection({
        aiModel,
        decisionModel: DECISION_MODELS.find((model) => model === stored?.decisionModel) ?? DEFAULT_DECISION_MODEL,
        reasoningEffort: normalizeEffort(aiModel, storedModel ? stored?.reasoningEffort : undefined),
      });
    } catch {
      // Preferences are optional when storage is unavailable or malformed.
    }
    setLoaded(true);
  }, []);
  useEffect(() => {
    if (!loaded) return;
    try {
      window.localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify(selection));
    } catch {
      // Storage restrictions must not prevent using the picker in this session.
    }
  }, [selection, loaded]);

  const value = useMemo<ModelSelectionValue>(() => ({
    ...selection,
    setAiModel: (aiModel) => setSelection((old) => ({ ...old, aiModel, reasoningEffort: DEFAULT_REASONING_EFFORT })),
    setModelEffort: (aiModel, effort) => setSelection((old) => ({ ...old, aiModel, reasoningEffort: normalizeEffort(aiModel, effort) })),
    setDecisionModel: (decisionModel) => setSelection((old) => ({ ...old, decisionModel })),
    headers: byok ? noHeaders : { "x-ai-model": selection.aiModel, "x-decision-model": selection.decisionModel, "x-reasoning-effort": selection.reasoningEffort },
    attributions, beginRun, attribute,
  }), [selection, byok, attributions, beginRun, attribute]);

  return <ModelSelectionContext.Provider value={value}>{children}</ModelSelectionContext.Provider>;
}

export function useModelSelection() {
  return useContext(ModelSelectionContext);
}

/** Freeze attribution before a run so subsequent picker changes never rewrite history. */
export function ModelAttributionRecorder() {
  const { agent } = useAgent();
  const { beginRun, attribute } = useModelSelection();
  useEffect(() => {
    let recording = false;
    let knownMessages = new Set<string>();
    const subscription = agent.subscribe({
      onRunInitialized: ({ messages }) => {
        beginRun();
        recording = true;
        knownMessages = new Set(messages.map((message) => message.id));
      },
      // Snapshot-based responses do not always emit onNewMessage.
      onMessagesChanged: ({ messages }) => {
        if (!recording) return;
        for (const message of messages) {
          if (message.role === "assistant" && !knownMessages.has(message.id)) attribute(message.id);
          knownMessages.add(message.id);
        }
      },
      onRunFinalized: () => { recording = false; },
    });
    return () => subscription.unsubscribe();
  }, [agent, beginRun, attribute]);
  return null;
}
