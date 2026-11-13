import { expect, it } from "vitest";
import { BRAND, brandedText } from "./branding";

it("uses the workbench name in both placeholder and legacy product copy", () => {
  expect(brandedText("欢迎使用 ArcReel；[[brand]] Agent")).toBe(`欢迎使用 ${BRAND.name}；${BRAND.name} Agent`);
});

it("preserves integration URLs, tool names and configuration paths", () => {
  const technical = "https://github.com/ArcReel/skills mcp__arcreel__read_source .arcreel/settings.json";
  expect(brandedText(technical)).toBe(technical);
});
