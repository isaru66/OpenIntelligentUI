import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { ModelSelectionProvider, MODEL_STORAGE_KEY, useModelSelection } from "./model-selection";
import { ModelChips, ModelSelectors } from "./model-dropdowns";
import { ProviderKeysProvider, useProviderKeys } from "./provider-keys";
import { AI_MODELS, EFFORT_LABELS, MODEL_EFFORTS, readModelHeaders } from "@/lib/model-headers";
import { buildRuntimeOptions } from "@/lib/copilotkit-runtime-options";

vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotChatInput: { AddMenuButton: () => null },
  CopilotChatAssistantMessage: () => null,
  useAgent: () => ({ agent: { subscribe: () => ({ unsubscribe() {} }) } }),
}));

function Probe() {
  const { headers, beginRun, attribute } = useModelSelection();
  const { save, clear } = useProviderKeys();
  return <>
    <output data-testid="headers">{JSON.stringify(headers)}</output>
    <button onClick={() => beginRun()}>begin</button>
    <button onClick={() => attribute("m1")}>attribute</button>
    <button onClick={() => { beginRun(); attribute("m1"); }}>run</button>
    <button onClick={() => save({ openai: "test", jev: "test" })}>byok</button>
    <button onClick={clear}>shared</button>
    <ModelChips messageId="m1" />
  </>;
}
function SelectionHarness() {
  const { hasKeys } = useProviderKeys();
  return <ModelSelectionProvider byok={hasKeys}><ModelSelectors /><Probe /></ModelSelectionProvider>;
}
const renderAll = () => render(<ProviderKeysProvider><SelectionHarness /></ProviderKeysProvider>);
const aiButton = () => screen.getByRole("button", { name: "AI model" });
function openEffort(model = "gpt-6-luna") {
  fireEvent.click(aiButton());
  fireEvent.click(screen.getByRole("menuitem", { name: `Configure effort for ${model}` }));
  return screen.getByRole("menu", { name: `Reasoning effort for ${model}` });
}
function chooseEffort(model: string, label: string) {
  const menu = openEffort(model);
  fireEvent.click(within(menu).getByRole("menuitemradio", { name: label }));
}
const headers = () => JSON.parse(screen.getByTestId("headers").textContent!);

beforeEach(() => { window.localStorage.clear(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("defaults to Medium and selects model names with keyboard at Medium", () => {
  renderAll();
  expect(aiButton()).toHaveTextContent("gpt-6-luna · Medium");
  expect(aiButton()).toHaveAttribute("aria-haspopup", "menu");
  fireEvent.keyDown(aiButton(), { key: "ArrowDown" });
  const menu = screen.getByRole("menu", { name: "AI model" });
  expect(within(menu).getByRole("menuitemradio", { checked: true })).toHaveFocus();
  fireEvent.keyDown(menu, { key: "ArrowDown" });
  expect(screen.getByRole("menuitem", { name: "Configure effort for gpt-6-luna" })).toHaveFocus();
  fireEvent.keyDown(menu, { key: "ArrowDown" });
  const sol = within(menu).getByRole("menuitemradio", { name: "gpt-6.1-sol" });
  expect(sol).toHaveFocus();
  fireEvent.click(sol);
  expect(aiButton()).toHaveTextContent("gpt-6.1-sol · Medium");
  expect(aiButton()).toHaveFocus();
  expect(headers()).toEqual({ "x-ai-model": "gpt-6.1-sol", "x-decision-model": "Microsoft-Decision-1", "x-reasoning-effort": "medium" });
});

it.each(AI_MODELS)("shows only supported efforts for %s without applying the previewed model", (model) => {
  renderAll();
  const menu = openEffort(model);
  expect(within(menu).getAllByRole("menuitemradio").map((o) => o.textContent?.replace("Default", "").trim()))
    .toEqual(MODEL_EFFORTS[model].map((effort) => EFFORT_LABELS[effort]));
  expect(headers()["x-ai-model"]).toBe("gpt-6-luna");
  expect(within(menu).getByRole("menuitemradio", { name: "Medium (default)" })).toHaveFocus();
  fireEvent.click(within(menu).getByRole("menuitemradio", { name: "Extra High" }));
  expect(headers()["x-ai-model"]).toBe(model);
  expect(headers()["x-reasoning-effort"]).toBe("xhigh");
  expect(aiButton()).toHaveFocus();
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("resets effort to Medium when explicitly selecting even the same model", () => {
  renderAll();
  chooseEffort("gpt-6-luna", "Max");
  fireEvent.click(aiButton());
  fireEvent.click(screen.getByRole("menuitemradio", { name: "gpt-6-luna" }));
  expect(headers()["x-reasoning-effort"]).toBe("medium");
});

it("supports submenu keyboard navigation, Escape and outside dismissal", () => {
  renderAll();
  fireEvent.click(aiButton());
  const parent = screen.getByRole("menu", { name: "AI model" });
  fireEvent.keyDown(parent, { key: "ArrowRight" });
  const submenu = screen.getByRole("menu", { name: "Reasoning effort for gpt-6-luna" });
  fireEvent.keyDown(submenu, { key: "End" });
  expect(within(submenu).getByRole("menuitemradio", { name: "Max" })).toHaveFocus();
  fireEvent.keyDown(submenu, { key: "Home" });
  expect(within(submenu).getByRole("menuitemradio", { name: "None" })).toHaveFocus();
  fireEvent.keyDown(submenu, { key: "Escape" });
  expect(screen.queryByRole("menu", { name: /Reasoning effort/ })).not.toBeInTheDocument();
  fireEvent.keyDown(parent, { key: "Escape" });
  expect(aiButton()).toHaveFocus();
  fireEvent.click(aiButton());
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
});

it("keeps decision listbox behavior unchanged", () => {
  renderAll();
  const button = screen.getByRole("button", { name: "Decision model" });
  fireEvent.click(button);
  const list = screen.getByRole("listbox", { name: "Decision model" });
  fireEvent.keyDown(list, { key: "ArrowDown" });
  fireEvent.keyDown(list, { key: "Enter" });
  expect(headers()["x-decision-model"]).toBe("Jev");
  expect(button).toHaveFocus();
});

it("persists selection and freezes model/effort attribution before the first reply", () => {
  renderAll();
  chooseEffort("gpt-6.1-sol", "High");
  fireEvent.click(screen.getByText("begin"));
  chooseEffort("claude-sonnet-5.5", "Max");
  fireEvent.click(screen.getByText("attribute"));
  expect(screen.getByTestId("model-chips")).toHaveTextContent("AI · gpt-6.1-sol · High");
  expect(JSON.parse(window.localStorage.getItem(MODEL_STORAGE_KEY)!)).toEqual({
    aiModel: "claude-sonnet-5.5", decisionModel: "Microsoft-Decision-1", reasoningEffort: "max",
  });
  cleanup();
  renderAll();
  expect(aiButton()).toHaveTextContent("claude-sonnet-5.5 · Max");
});

it.each([
  [{ aiModel: "claude-sonnet-5.5" }, "claude-sonnet-5.5 · Medium"],
  [{ aiModel: "gpt-6.1-sol", reasoningEffort: "none" }, "gpt-6.1-sol · Medium"],
  [{ aiModel: "unknown", reasoningEffort: "invalid" }, "gpt-6-luna · Medium"],
  [{ aiModel: "unknown", reasoningEffort: "max" }, "gpt-6-luna · Medium"],
  [null, "gpt-6-luna · Medium"],
])("migrates old or invalid stored selection %j", (stored, label) => {
  window.localStorage.setItem(MODEL_STORAGE_KEY, JSON.stringify(stored));
  renderAll();
  expect(aiButton()).toHaveTextContent(label);
});

it("disables BYOK controls, omits shared overrides and attributes actual fixed models", () => {
  renderAll();
  chooseEffort("gpt-6.1-sol", "High");
  fireEvent.click(screen.getByText("byok"));
  expect(aiButton()).toBeDisabled();
  expect(aiButton()).toHaveTextContent("chat-latest");
  expect(screen.getByRole("button", { name: "Decision model" })).toBeDisabled();
  expect(aiButton()).toHaveAccessibleDescription(/server-configured providers/);
  expect(headers()).toEqual({});
  fireEvent.click(screen.getByText("run"));
  expect(screen.getByTestId("model-chips")).toHaveTextContent("AI · chat-latest");
  expect(screen.getByTestId("model-chips")).not.toHaveTextContent("High");
  fireEvent.click(screen.getByText("shared"));
  expect(aiButton()).toHaveTextContent("gpt-6.1-sol · High");
});

it.each(AI_MODELS)("forwards every supported effort for %s through the runtime", (model) => {
  for (const effort of MODEL_EFFORTS[model]) {
    const read = readModelHeaders(new Headers({ "x-ai-model": model, "x-reasoning-effort": effort, "x-decision-model": "Jev" }));
    const agent = buildRuntimeOptions({ modelHeaders: read }).agents.default;
    expect(agent.headers).toMatchObject({ "x-ai-model": model, "x-reasoning-effort": effort, "x-decision-model": "Jev" });
  }
});

it("normalizes malformed, missing and unsupported effort without enabling unknown models", () => {
  expect(readModelHeaders(new Headers({ "x-ai-model": "gpt-6.1-sol", "x-reasoning-effort": "none" })))
    .toEqual({ "x-ai-model": "gpt-6.1-sol", "x-reasoning-effort": "medium" });
  const duplicate = new Headers({ "x-ai-model": "gpt-6-luna" });
  duplicate.append("x-reasoning-effort", "high");
  duplicate.append("x-reasoning-effort", "low");
  expect(readModelHeaders(duplicate)["x-reasoning-effort"]).toBe("medium");
  expect(readModelHeaders(new Headers({ "x-reasoning-effort": "high", "x-ai-model": "unknown" }))).toEqual({});
  expect(readModelHeaders(new Headers())).toEqual({});
});

it("returns from the narrow-screen effort panel without changing selection", () => {
  vi.stubGlobal("innerWidth", 375);
  renderAll();
  openEffort("gpt-6.1-sol");
  expect(document.querySelector(".ai-model-menu")).toHaveAttribute("data-hidden", "true");
  fireEvent.click(screen.getByRole("button", { name: "Back to models" }));
  expect(document.querySelector(".ai-model-menu")).not.toHaveAttribute("data-hidden");
  expect(headers()["x-ai-model"]).toBe("gpt-6-luna");
});

it("returns focus to the chevron and tabs out of the entire menu", async () => {
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue(Object.assign([new DOMRect()], { item: () => null }));
  renderAll();
  const menu = openEffort();
  fireEvent.keyDown(menu, { key: "ArrowLeft" });
  await vi.waitFor(() => expect(screen.getByRole("menuitem", { name: "Configure effort for gpt-6-luna" })).toHaveFocus());
  fireEvent.keyDown(screen.getByRole("menu", { name: "AI model" }), { key: "Tab" });
  expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Decision model" })).toHaveFocus();
});
