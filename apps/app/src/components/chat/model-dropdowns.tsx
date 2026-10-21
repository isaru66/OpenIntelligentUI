"use client";

import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
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
import { EFFORT_LABELS, MODEL_EFFORTS, type ReasoningEffort } from "@/lib/model-headers";
import { useProviderKeys } from "./provider-keys";

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
  describedBy?: string;
};

export function ModelDropdown<T extends string>({ label, options, value, onChange, icon: leading, disabled, describedBy }: DropdownProps<T>) {
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
        aria-describedby={describedBy}
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

function AiModelMenu({ disabled, describedBy }: { disabled: boolean; describedBy?: string }) {
  const { aiModel, reasoningEffort, setAiModel, setModelEffort } = useModelSelection();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<AiModel | null>(null);
  const [position, setPosition] = useState({ left: 0, top: 0 });
  const [narrow, setNarrow] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const submenu = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const id = useId();

  useEffect(() => {
    const resize = () => setNarrow(window.innerWidth <= 600);
    resize();
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  useEffect(() => {
    if (!open) return;
    const outside = (event: Event) => {
      if (!root.current?.contains(event.target as Node)) { setOpen(false); setTarget(null); }
    };
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open]);
  useLayoutEffect(() => {
    if (!open) return;
    if (target) (submenu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
      ?? submenu.current?.querySelector<HTMLButtonElement>('[data-default]'))?.focus();
    else menu.current?.querySelector<HTMLButtonElement>('[aria-checked="true"]')?.focus();
  }, [open, target, narrow]);
  useLayoutEffect(() => {
    if (!open || !target || narrow) return;
    const place = () => {
      const anchor = menu.current?.parentElement?.getBoundingClientRect();
      const panel = submenu.current?.getBoundingClientRect();
      if (!anchor || !panel) return;
      const left = anchor.right + panel.width + 8 <= window.innerWidth - 16
        ? anchor.right + 8 : anchor.left - panel.width - 8;
      setPosition({
        left: Math.max(16, Math.min(left, window.innerWidth - panel.width - 16)),
        top: Math.max(16, Math.min(anchor.top, window.innerHeight - panel.height - 16)),
      });
    };
    place();
    window.addEventListener("resize", place);
    window.addEventListener("scroll", place, true);
    return () => { window.removeEventListener("resize", place); window.removeEventListener("scroll", place, true); };
  }, [open, target, narrow]);

  const close = () => { setOpen(false); setTarget(null); trigger.current?.focus(); };
  const back = () => { setTarget(null); requestAnimationFrame(() => opener.current?.focus()); };
  const keyNavigation = (event: KeyboardEvent<HTMLDivElement>, inSubmenu: boolean) => {
    const panel = event.currentTarget;
    if (event.key === "Escape") {
      event.preventDefault(); event.stopPropagation();
      if (inSubmenu) back(); else close();
      return;
    }
    if (event.key === "Tab") {
      const outside = Array.from(document.querySelectorAll<HTMLElement>('a[href], button, input, select, textarea, [tabindex]'))
        .filter((element) => element.tabIndex >= 0 && !element.hasAttribute("disabled") && element.getClientRects().length > 0
          && (element === trigger.current || !root.current?.contains(element)));
      const index = trigger.current ? outside.indexOf(trigger.current) : -1;
      const next = outside[index + (event.shiftKey ? -1 : 1)];
      event.preventDefault();
      setOpen(false); setTarget(null);
      (next ?? trigger.current)?.focus();
      return;
    }
    if (inSubmenu && event.key === "ArrowLeft") { event.preventDefault(); back(); return; }
    const buttons = Array.from(panel.querySelectorAll<HTMLButtonElement>('[role^="menuitem"]'));
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    let next: number | undefined;
    if (event.key === "ArrowDown") next = (index + 1) % buttons.length;
    if (event.key === "ArrowUp") next = (index - 1 + buttons.length) % buttons.length;
    if (event.key === "Home") next = 0;
    if (event.key === "End") next = buttons.length - 1;
    if (next !== undefined) { event.preventDefault(); buttons[next]?.focus(); }
    if (!inSubmenu && event.key === "ArrowRight") {
      const active = buttons[index];
      const model = AI_MODELS.find((model) => model === active?.dataset.model);
      if (model) {
        event.preventDefault();
        opener.current = panel.querySelector<HTMLButtonElement>(`[data-effort-model="${model}"]`);
        setTarget(model);
      }
    }
  };

  return <div className="model-dropdown" data-open={open || undefined} ref={root}>
    <span className="model-dropdown__label" aria-hidden="true">AI model</span>
    <button ref={trigger} type="button" className="model-dropdown__button" aria-label="AI model"
      aria-describedby={describedBy} aria-haspopup="menu" aria-expanded={open}
      aria-controls={open ? id : undefined} disabled={disabled}
      onClick={() => { setTarget(null); setOpen(!open); }}
      onKeyDown={(event) => {
        if (event.key === "ArrowDown" || event.key === "ArrowUp") { event.preventDefault(); setOpen(true); }
      }}>
      <span className="model-dropdown__icon"><SparklesIcon /></span>
      <span className="model-dropdown__value">{disabled ? "chat-latest" : `${aiModel} · ${EFFORT_LABELS[reasoningEffort]}`}</span>
      <ChevronIcon />
    </button>
    {open && !disabled && <>
      <div className="model-dropdown__menu ai-model-menu" data-hidden={narrow && target ? true : undefined}>
        <div ref={menu} id={id} role="menu" aria-label="AI model" onKeyDown={(event) => keyNavigation(event, false)}>
          {AI_MODELS.map((model) => <div key={model} className="ai-model-menu__row">
            <button type="button" role="menuitemradio" tabIndex={-1} aria-checked={model === aiModel} data-model={model}
              className="model-dropdown__option ai-model-menu__select" onClick={() => { setAiModel(model); close(); }}>
              <span className="model-dropdown__option-text">{model}</span>
              {model === aiModel && <span className="model-dropdown__check"><CheckIcon /></span>}
            </button>
            <button type="button" role="menuitem" tabIndex={-1} data-model={model} data-effort-model={model}
              className="ai-model-menu__chevron" aria-label={`Configure effort for ${model}`}
              aria-haspopup="menu" aria-expanded={target === model} aria-controls={target === model ? `${id}-effort` : undefined}
              onClick={(event) => { opener.current = event.currentTarget; setTarget(model); }}>
              <ChevronIcon />
            </button>
          </div>)}
        </div>
      </div>
      {target && <div className="model-dropdown__menu effort-menu" ref={submenu}
        style={narrow ? undefined : { left: position.left, top: position.top }}
        aria-labelledby={`${id}-heading`} onKeyDown={(event) => keyNavigation(event, true)}>
        <button type="button" className="effort-menu__back" onClick={back}>Back to models</button>
        <div className="effort-menu__heading" id={`${id}-heading`}>Reasoning effort</div>
        <div className="effort-menu__model">{target}</div>
        <div id={`${id}-effort`} role="menu" aria-label={`Reasoning effort for ${target}`}
          aria-describedby={`${id}-help`}>
          {MODEL_EFFORTS[target].map((effort: ReasoningEffort) => <button key={effort} type="button"
            role="menuitemradio" tabIndex={-1} aria-label={`${EFFORT_LABELS[effort]}${effort === "medium" ? " (default)" : ""}`}
            aria-checked={target === aiModel && effort === reasoningEffort}
            data-default={effort === "medium" ? true : undefined} className="model-dropdown__option effort-menu__option"
            onClick={() => { setModelEffort(target, effort); close(); }}>
            <span className="model-dropdown__option-text">{EFFORT_LABELS[effort]}</span>
            {effort === "medium" && <span className="effort-menu__default">{" "}Default</span>}
            {target === aiModel && effort === reasoningEffort && <span className="model-dropdown__check"><CheckIcon /></span>}
          </button>)}
        </div>
        <p className="effort-menu__help" id={`${id}-help`}>Higher effort may take longer and use more tokens.</p>
      </div>}
    </>}
  </div>;
}

export function ModelSelectors() {
  const { decisionModel, setDecisionModel } = useModelSelection();
  const { hasKeys } = useProviderKeys();
  const helpId = useId();
  return (
    <div className="model-selectors">
      <AiModelMenu key={hasKeys ? "byok-ai" : "shared-ai"} disabled={hasKeys} describedBy={hasKeys ? helpId : undefined} />
      <ModelDropdown<DecisionModel> key={hasKeys ? "byok-decision" : "shared-decision"} label="Decision model" options={DECISION_MODELS} value={hasKeys ? "Jev" : decisionModel} onChange={setDecisionModel} icon={<GitBranchIcon />} disabled={hasKeys} describedBy={hasKeys ? helpId : undefined} />
      {hasKeys && <span id={helpId} className="model-selectors__help">Custom model and effort selection is available with server-configured providers.</span>}
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
      <span className="model-chip">AI · {used.aiModel}{used.reasoningEffort && ` · ${EFFORT_LABELS[used.reasoningEffort]}`}</span>
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