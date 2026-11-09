import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ChapterNote } from "@/types/novel-workflow";
import { CrossChapterPanel } from "./CrossChapterPanel";

it("distinguishes story applicability from later reader revelation and shows both original citations", () => {
  const select = vi.fn();
  const notes = [1, 2].map((i) => ({ id: `n${i}`, title: `第${i}章` })) as ChapterNote[];
  render(<CrossChapterPanel notes={notes} select={select} value={{ reports: [], links: [{ id: "link", kind: "identity", subject: "陌生人 / 景麒", description: "后文确认身份", status: "supported", story_time: "第一章出现时", story_start_note_id: "n1", story_end_note_id: null, note_ids: ["n1", "n2"], revealed_at: { note_id: "n2", order: 2, offset: 99 }, evidence: [{ note_id: "n1", source_file: "source/book.txt", start: 1, end: 10, quote: "门边站着陌生人。" }, { note_id: "n2", source_file: "source/book.txt", start: 80, end: 99, quote: "那人就是景麒。" }] }] }} />);
  expect(screen.getByText("第一章出现时")).toBeInTheDocument();
  expect(screen.getByText("第2章 · 99")).toBeInTheDocument();
  expect(screen.getByText("门边站着陌生人。")).toBeInTheDocument();
  expect(screen.getByText("那人就是景麒。")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "选择来源 Note" }));
  expect(select).toHaveBeenCalledWith(["n1", "n2"]);
});
