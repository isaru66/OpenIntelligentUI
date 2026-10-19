import { describe, it, expect } from "vitest";
import { OPEN_GEN_UI_DESIGN_SKILL } from "../index.js";

describe("OPEN_GEN_UI_DESIGN_SKILL", () => {
  it("is a non-empty string", () => {
    expect(typeof OPEN_GEN_UI_DESIGN_SKILL).toBe("string");
    expect(OPEN_GEN_UI_DESIGN_SKILL.length).toBeGreaterThan(0);
  });

  it("references the design-system color tokens", () => {
    expect(OPEN_GEN_UI_DESIGN_SKILL).toContain("--color-background-primary");
  });

  it("references the SVG color-ramp classes", () => {
    expect(OPEN_GEN_UI_DESIGN_SKILL).toContain(".c-purple");
  });

  it("explains automatic dark mode", () => {
    expect(OPEN_GEN_UI_DESIGN_SKILL.toLowerCase()).toContain("dark mode");
  });

  it("does not carry over the canonical shadcn guidance", () => {
    expect(OPEN_GEN_UI_DESIGN_SKILL.toLowerCase()).not.toContain("shadcn");
  });
});

import { OPEN_GEN_UI_DESIGN_SKILL as NITRO_SKILL } from "../index.js";

describe("nitro design skill", () => {
  it("documents the nitro theme and theme-aware JS colors", () => {
    expect(NITRO_SKILL).toContain("nitro");
    expect(NITRO_SKILL).toContain("getComputedStyle");
    expect(NITRO_SKILL).toContain("dataset.theme");
  });

  it("guides using --color-background-secondary for cards/panels on the white light-mode canvas", () => {
    expect(NITRO_SKILL).toContain("--color-background-secondary");
    expect(NITRO_SKILL).toContain("#FFFFFF");
    expect(NITRO_SKILL).toContain("--color-background-tertiary");
  });
});
