"use client";

import { createContext, useContext, useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { CopilotChatInput, CopilotChatAssistantMessage } from "@copilotkit/react-core/v2";
import type { ComponentProps } from "react";
import {
  AI_MODELS,
  DECISION_MODELS,
  useModelSelection,
  type AiModel,
  type DecisionModel,
} from "./model-selection";
import "./model-selectors.css";

const icon = { width: 14, height: 14, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true, focusable: false } as const;
export const SparklesIcon = () => <svg {...icon}><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z" /></svg>;
export const GitBranchIcon = () => <svg {...icon}><line x1="6" x2="6" y1="3" y2="15" /><circle cx="18" cy="6" r="3" /><circle cx="6" cy="18" r="3" /><path d="M18 9a9 9 0 0 1-9 9" /></svg>;
const ChevronIcon = () => <svg {...icon}><path d="m6 9 6 6 6-6" /></svg>;
const CheckIcon = () => <svg {...icon}><path d="M20 6 9 17l-5-5" /></svg>;

type DropdownProps<T extends string> = {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (value: T) => void;
  icon: ReactNode;
  disabled?: boolean;
};

export function ModelDropdown<T extends string>({ label, options, value, onChange, icon: leading, disabled }: DropdownProps<T>) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const id = useId();

  useEffect(() => {
    if (!open) return;
    const close = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("mousedown", close);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("mousedown", close);
    };
  }, [open]);
  useEffect(() => { if (open) list.current?.focus(); }, [open]);

  const show = () => { setActive(Math.max(0, options.indexOf(value))); setOpen(true); };
  const choose = (option: T) => { onChange(option); setOpen(false); button.current?.focus(); };
  const onButtonKey = (event: KeyboardEvent) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); show(); }
  };
  const onListKey = (event: KeyboardEvent) => {
    const last = options.length - 1;
    switch (event.key) {
      case "ArrowDown": event.preventDefault(); setActive((i) => Math.min(i + 1, last)); break;
      case "ArrowUp": event.preventDefault(); setActive((i) => Math.max(i - 1, 0)); break;
      case "Home": event.preventDefault(); setActive(0); break;
      case "End": event.preventDefault(); setActive(last); break;
      case "Enter": case " ": event.preventDefault(); choose(options[active]); break;
      case "Escape": event.preventDefault(); event.stopPropagation(); setOpen(false); button.current?.focus(); break;
      case "Tab": setOpen(false); break;
    }
  };

  return (
    <div className="model-dropdown" data-open={open || undefined} ref={root}>
      <span className="model-dropdown__label" aria-hidden="true">{label}</span>
      <button
        ref={button}
        type="button"
        className="model-dropdown__button"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={onButtonKey}
      >
        <span className="model-dropdown__icon">{leading}</span>
        <span className="model-dropdown__value">{value}</span>
        <ChevronIcon />
      </button>
      {open && (
        <ul
          ref={list}
          id={id}
          role="listbox"
          tabIndex={-1}
          aria-label={label}
          aria-activedescendant={`${id}-${active}`}
          className="model-dropdown__menu"
          onKeyDown={onListKey}
        >
          {options.map((option, index) => (
            <li
              key={option}
              id={`${id}-${index}`}
              role="option"
              aria-selected={option === value}
              data-active={index === active || undefined}
              className="model-dropdown__option"
              onPointerMove={() => setActive(index)}
              onClick={() => choose(option)}
            >
              <span className="model-dropdown__icon">{leading}</span>
              <span className="model-dropdown__option-text">{option}</span>
              {option === value && <span className="model-dropdown__check" data-testid="selected-check"><CheckIcon /></span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ModelSelectors() {
  const { aiModel, decisionModel, setAiModel, setDecisionModel } = useModelSelection();
  return (
    <div className="model-selectors">
      <ModelDropdown<AiModel> label="AI model" options={AI_MODELS} value={aiModel} onChange={setAiModel} icon={<SparklesIcon />} />
      <ModelDropdown<DecisionModel> label="Decision model" options={DECISION_MODELS} value={decisionModel} onChange={setDecisionModel} icon={<GitBranchIcon />} />
    </div>
  );
}

/** Rendered in the input's add-button slot so CopilotKit keeps its own layout and textarea sizing. */
export function PromptAddMenu(props: ComponentProps<typeof CopilotChatInput.AddMenuButton>) {
  return <>
    <CopilotChatInput.AddMenuButton {...props} />
    <ModelSelectors />
  </>;
}

export function ModelChips({ messageId }: { messageId: string }) {
  const { attributions } = useModelSelection();
  const used = attributions[messageId];
  if (!used) return null;
  return (
    <div className="model-chips" data-testid="model-chips">
      <span className="model-chip">AI · {used.aiModel}</span>
      <span className="model-chip">Decision · {used.decisionModel}</span>
    </div>
  );
}

/** Carries the host's own assistantMessage slot value so the stable chip wrapper can honour it. */
export const AssistantSlotContext = createContext<unknown>(undefined);

export function AssistantMessageWithChips(props: ComponentProps<typeof CopilotChatAssistantMessage>) {
  const slot = useContext(AssistantSlotContext);
  const Custom = typeof slot === "function" ? (slot as typeof CopilotChatAssistantMessage) : CopilotChatAssistantMessage;
  const overrides = slot && typeof slot === "object" ? (slot as Partial<ComponentProps<typeof CopilotChatAssistantMessage>>) : {};
  return <>
    <Custom {...overrides} {...props} />
    <ModelChips messageId={props.message.id} />
  </>;
}