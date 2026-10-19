"use client";

import { CopilotChatView } from "@copilotkit/react-core/v2";
import type { ComponentProps } from "react";
import { AssistantMessageWithChips, AssistantSlotContext, PromptAddMenu } from "./model-dropdowns";
import { useProviderKeys } from "./provider-keys";

type ViewProps = ComponentProps<typeof CopilotChatView>;
const isSlotObject = (value: unknown): value is Record<string, unknown> =>
  value === undefined || (typeof value === "object" && value !== null);

/** Gate submission before CopilotKit adds a message or starts a provider request. */
function KeyGatedChatViewComponent(props: ViewProps) {
  const { hasKeys, requireKeys, draft, setDraft, setKeysOpen } = useProviderKeys();
  const { input, messageView } = props;
  const messageViewObject = isSlotObject(messageView) ? (messageView as Record<string, unknown> | undefined) : undefined;
  return <AssistantSlotContext.Provider value={messageViewObject?.assistantMessage}>
    <CopilotChatView
      {...props}
      input={isSlotObject(input) ? { ...(input as object), addMenuButton: PromptAddMenu } : input}
      messageView={isSlotObject(messageView) ? ({ ...(messageView as object), assistantMessage: AssistantMessageWithChips } as ViewProps["messageView"]) : messageView}
      inputValue={draft}
      onInputChange={setDraft}
      onSubmitMessage={(value) => {
        if (requireKeys && !hasKeys) {
          setDraft(value);
          setKeysOpen(true);
          return;
        }
        setDraft("");
        props.onSubmitMessage?.(value);
      }}
      onSelectSuggestion={(suggestion, index) => {
        if (requireKeys && !hasKeys) {
          setDraft(suggestion.message);
          setKeysOpen(true);
          return;
        }
        setDraft("");
        props.onSelectSuggestion?.(suggestion, index);
      }}
    />
  </AssistantSlotContext.Provider>;
}

// Keep the compound-component slots expected by CopilotKit’s chatView contract.
export const KeyGatedChatView = Object.assign(KeyGatedChatViewComponent, CopilotChatView);