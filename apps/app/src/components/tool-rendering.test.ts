import { describe, expect, it } from "vitest";
import { getSkillName } from "./tool-rendering";

describe("getSkillName", () => {
  it("extracts the skill name from SKILL.md reads", () => {
    expect(
      getSkillName("read_file", { file_path: "/skills/advanced-visualization/SKILL.md" }),
    ).toBe("advanced-visualization");
  });

  it("ignores other files and tools", () => {
    expect(getSkillName("read_file", { file_path: "/skills/x/other.md" })).toBeNull();
    expect(getSkillName("ls", { file_path: "/skills/x/SKILL.md" })).toBeNull();
    expect(getSkillName("read_file", undefined)).toBeNull();
  });
});
