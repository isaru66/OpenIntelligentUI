import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { ThemeProvider } from "@/hooks/use-theme";
import { ThemeSwitcher } from "./theme-switcher";

let systemDark = false;
beforeEach(() => {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: systemDark,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  systemDark = false;
  document.documentElement.removeAttribute("class");
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-theme-name");
});

function renderSwitcher() {
  render(
    <ThemeProvider>
      <ThemeSwitcher />
    </ThemeProvider>,
  );
}

it("exposes pressed state and updates document theme attributes", () => {
  renderSwitcher();
  const group = screen.getByRole("group", { name: "Theme mode" });
  expect(group).toBeInTheDocument();
  const root = document.documentElement;
  expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "true");
  expect(root.dataset.theme).toBe("light");
  expect(root.dataset.themeName).toBe("nitro");

  fireEvent.click(screen.getByRole("button", { name: "Dark" }));
  expect(screen.getByRole("button", { name: "Dark" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "false");
  expect(root.dataset.theme).toBe("dark");
  expect(root).toHaveClass("dark");
});

it("resolves System to the OS color scheme", () => {
  systemDark = true;
  renderSwitcher();
  fireEvent.click(screen.getByRole("button", { name: "System" }));
  expect(screen.getByRole("button", { name: "System" })).toHaveAttribute("aria-pressed", "true");
  expect(document.documentElement.dataset.theme).toBe("dark");
});
