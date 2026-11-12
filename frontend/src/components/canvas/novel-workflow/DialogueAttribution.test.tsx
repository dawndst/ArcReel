import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { DialogueAttribution } from "./DialogueAttribution";
import type { LibraryShot } from "@/types/novel-workflow";
it("keeps AI advice read-only until explicitly adopted and passes the current shot revision", () => {
  const attribute = vi.fn();
  const shot = { id: "sh", revision: "current", speaker_suggestions: { items: [{ segment_index: 0, utterance_index: 1, speaker: "阳子", source_quote: "阳子喊道", reason: "原文明示" }] } } as LibraryShot;
  render(<DialogueAttribution shot={shot} segment={0} utterance={1} characters={["阳子"]} disabled={false} attribute={attribute} />);
  expect(screen.getByText("阳子喊道")).toBeInTheDocument();
  expect(attribute).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "采用：阳子" }));
  expect(attribute).toHaveBeenCalledWith("sh", 0, 1, "阳子", "current");
});
it("does not offer adoption for an unresolved attribution", () => {
  const shot = { id: "sh", speaker_suggestions: { items: [{ segment_index: 0, utterance_index: 0, speaker: null, source_quote: "", reason: "没有足够依据" }] } } as LibraryShot;
  render(<DialogueAttribution shot={shot} segment={0} utterance={0} characters={[]} disabled={false} />);
  expect(screen.getByText("没有足够依据")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /^采用/ })).not.toBeInTheDocument();
});
