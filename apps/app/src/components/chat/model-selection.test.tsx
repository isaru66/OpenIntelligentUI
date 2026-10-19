import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { ModelSelectionProvider, MODEL_STORAGE_KEY, useModelSelection } from "./model-selection";
import { ModelChips, ModelSelectors } from "./model-dropdowns";
import { readModelHeaders } from "@/lib/model-headers";
import { buildRuntimeOptions } from "@/lib/copilotkit-runtime-options";

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatInput: { AddMenuButton: () => null },
  CopilotChatAssistantMessage: () => null,
  useAgent: () => ({ agent: { subscribe: () => ({ unsubscribe() {} }) } }),
}));

function Probe() {
  const { headers, beginRun, attribute, aiModel } = useModelSelection();
  return <>
    <output data-testid="headers">{JSON.stringify(headers)}</output>
    <output data-testid="ai">{aiModel}</output>
    <button onClick={() => { beginRun(); attribute("m1"); }}>run</button>
    <ModelChips messageId="m1" />
    <ModelChips messageId="m2" />
  </>;
}
const renderAll = () => render(<ModelSelectionProvider><ModelSelectors /><Probe /></ModelSelectionProvider>);

beforeEach(() => window.localStorage.clear());
afterEach(cleanup);

it("opens a listbox with a check on the selected option and selects with keyboard", () => {
  renderAll();
  const button = screen.getByRole("button", { name: "AI model" });
  expect(button).toHaveAttribute("aria-haspopup", "listbox");
  expect(button).toHaveAttribute("aria-expanded", "false");
  fireEvent.click(button);
  const list = screen.getByRole("listbox", { name: "AI model" });
  expect(within(list).getAllByRole("option").map((o) => o.textContent)).toEqual(["gpt-6-luna", "gpt-6.1-sol", "claude-sonnet-5.5"]);
  const selected = within(list).getByRole("option", { selected: true });
  expect(selected).toHaveTextContent("gpt-6-luna");
  expect(within(selected).getByTestId("selected-check")).toBeInTheDocument();
  fireEvent.keyDown(list, { key: "ArrowDown" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(button).toHaveTextContent("gpt-6.1-sol");
  expect(button).toHaveFocus();
  expect(screen.getByTestId("ai")).toHaveTextContent("gpt-6.1-sol");
});

it("closes on Escape and outside click", () => {
  renderAll();
  const button = screen.getByRole("button", { name: "Decision model" });
  fireEvent.click(button);
  expect(screen.getByRole("listbox", { name: "Decision model" })).toBeInTheDocument();
  fireEvent.keyDown(screen.getByRole("listbox"), { key: "Escape" });
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  fireEvent.click(button);
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

it("keeps aria-labels and shows visible labels only through hover/focus CSS", () => {
  renderAll();
  const label = document.querySelector(".model-dropdown__label");
  expect(label).toHaveTextContent("AI model");
  expect(screen.getByRole("button", { name: "AI model" })).toBeInTheDocument();
  const css = readFileSync(join(__dirname, "model-selectors.css"), "utf8");
  expect(css).toMatch(/\.model-dropdown__label\s*{[^}]*opacity:\s*0/);
  expect(css).toMatch(/\.model-dropdown:hover \.model-dropdown__label[^{]*,[^{]*:focus-within \.model-dropdown__label[^{]*{[^}]*opacity:\s*1/);
  expect(css).toMatch(/width:\s*260px/);
});

it("exposes headers, persists the selection, and keeps earlier reply chips unchanged", () => {
  renderAll();
  fireEvent.click(screen.getByText("run"));
  expect(screen.getByTestId("model-chips")).toHaveTextContent("AI · gpt-6-luna");
  expect(screen.getByTestId("model-chips")).toHaveTextContent("Decision · Microsoft-Decision-1");
  fireEvent.click(screen.getByRole("button", { name: "Decision model" }));
  fireEvent.click(screen.getByRole("option", { name: "Jev" }));
  expect(JSON.parse(screen.getByTestId("headers").textContent!)).toEqual({ "x-ai-model": "gpt-6-luna", "x-decision-model": "Jev" });
  expect(screen.getByTestId("model-chips")).toHaveTextContent("Decision · Microsoft-Decision-1");
  expect(JSON.parse(window.localStorage.getItem(MODEL_STORAGE_KEY)!)).toEqual({ aiModel: "gpt-6-luna", decisionModel: "Jev" });
});

it("restores a stored selection and ignores unknown stored values", () => {
  window.localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify({ aiModel: "claude-sonnet-5.5", decisionModel: "bogus" }));
  renderAll();
  expect(screen.getByRole("button", { name: "AI model" })).toHaveTextContent("claude-sonnet-5.5");
  expect(screen.getByRole("button", { name: "Decision model" })).toHaveTextContent("Microsoft-Decision-1");
});

it("forwards only allowlisted model headers to the agent", () => {
  const read = readModelHeaders(new Headers({ "x-ai-model": "gpt-6.1-sol", "x-decision-model": "evil" }));
  expect(read).toEqual({ "x-ai-model": "gpt-6.1-sol" });
  const options = buildRuntimeOptions({ modelHeaders: read, providerHeaders: { "x-openai-api-key": "a", "x-jev-api-key": "b" } });
  const agent = options.agents.default as unknown as { headers: Record<string, string> };
  expect(agent.headers).toEqual({ "x-ai-model": "gpt-6.1-sol", "x-openai-api-key": "a", "x-jev-api-key": "b" });
  expect(buildRuntimeOptions({ modelHeaders: {} }).agents.default).toBeDefined();
});
