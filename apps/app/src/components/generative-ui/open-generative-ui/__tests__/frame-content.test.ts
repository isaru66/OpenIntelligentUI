import { describe, expect, it } from "vitest";
import { buildFinalFrameContent, buildThemeScript } from "../frame-content";

describe("theme script", () => {
  it("sets data-theme and the nitro theme name", () => {
    const script = buildThemeScript("dark");
    expect(script).toContain('"data-theme", "dark"');
    expect(script).toContain('"data-theme-name", "nitro"');
  });

  it("is embedded in the final frame with the requested theme", () => {
    const html = buildFinalFrameContent("<body></body>", undefined, "dark");
    expect(html).toContain('"data-theme", "dark"');
    expect(html).toContain("nitro");
  });
});
