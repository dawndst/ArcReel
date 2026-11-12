import { expect, it } from "vitest";
import { sourceExcerptDisplay } from "./source-excerpt";
it("compacts EPUB spacing while retaining both original dialogue and narration", () => {
  const original = '“早上好。”\n\n\n\n\u00a0\u00a0\u00a0\u00a0阳子一进教室就大声道了声“早安！”。';
  expect(sourceExcerptDisplay(original)).toBe('“早上好。”\n\n阳子一进教室就大声道了声“早安！”。');
});
