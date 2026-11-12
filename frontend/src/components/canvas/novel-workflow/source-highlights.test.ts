import { expect, it } from "vitest";
import { highlightedSource } from "./source-highlights";
it("uses source code-point offsets and preserves the full original including astral characters", () => {
  const text = "前😀阳子说：走吧。后文";
  const result = highlightedSource(text, 100, { start: 102, end: 109 }, [{ start: 106, end: 108 }]);
  expect(result.map((p) => p.text).join("")).toBe(text);
  expect(result.filter((p) => p.focus).map((p) => p.text).join("")).toBe("走吧");
});
it("keeps repeated dialogue matches separate and clamps partial source evidence", () => {
  const result = highlightedSource("台辅。中间。台辅。", 10, { start: 0, end: 14 }, [{ start: 10, end: 12 }, { start: 16, end: 18 }]);
  expect(result.filter((p) => p.focus).map((p) => p.text)).toEqual(["台辅", "台辅"]);
  expect(result.map((p) => p.text).join("")).toBe("台辅。中间。台辅。");
});
