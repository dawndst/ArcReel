import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { API } from "@/api";
import { SceneBatchSource } from "./SceneBatchSource";

it("opens the actual batch source without navigating to a collapsed Note", async () => {
  const get = vi.spyOn(API, "getSceneBatchSource").mockResolvedValue({ text: "当前片段准确原文", source_file: "book", start: 100, end: 108, note_title: "第一章", part: 2, shots: [] });
  render(<SceneBatchSource projectName="p" basis="batch" close={() => {}} />);
  expect(await screen.findByText("当前片段准确原文")).toBeInTheDocument();
  expect(get).toHaveBeenCalledWith("p", "batch");
  expect(screen.getByText("book · 100–108")).toBeInTheDocument();
});


it("scrolls to the dialogue rather than the earlier context highlight", async () => {
  vi.spyOn(API, "getSceneBatchSource").mockResolvedValue({ text: "上下文对白后文", source_file: "book", start: 0, end: 7, note_title: "第一章", part: 1,
    shots: [{ id: "SH-001", title: "问候", start: 0, end: 7, dialogues: [{ segment: 1, utterance: 1, text: "对白", ranges: [{ start: 3, end: 5 }] }] }] });
  const scroll = vi.spyOn(Element.prototype, "scrollIntoView");
  render(<SceneBatchSource projectName="p" basis="batch" shotId="SH-001" segment={1} utterance={1} close={() => {}} />);
  const focus = await screen.findByText("对白", { selector: "mark" });
  expect(scroll.mock.instances.at(-1)).toBe(focus);
  expect(focus).toHaveClass("underline");
  expect(screen.getByRole("dialog")).toHaveAttribute("data-size", "xl");
});
