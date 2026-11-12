import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { API } from "@/api";
import type { ChapterNote, ChapterEdition } from "@/types/novel-workflow";
import { ChapterEditionPanel } from "./ChapterEditionPanel";

it("loads edition lazily and exposes omitted original text", async () => {
  const edition: ChapterEdition = { basis: "e", original_chars: 100, edited_chars: 20, created_at: "now", parts: [{ source_file: "book", start: 0, end: 100, passages: [{ unit: 0, treatment: "omit", text: "", reason: "重复描写", original_quote: "仍可回查的原文", evidence: { source_file: "book", start: 0, end: 100 }, protected: false }] }] };
  const note = { id: "n", edition } as ChapterNote;
  const get = vi.spyOn(API, "getChapterEdition").mockResolvedValue(edition);
  render(<ChapterEditionPanel projectName="p" note={note} disabled={false} generate={() => {}} />);
  expect(get).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "阅读精编稿" }));
  expect(await screen.findByText("已省略，可回读 · 原文依据")).toBeInTheDocument();
  fireEvent.click(screen.getByText("已省略，可回读 · 原文依据"));
  expect(screen.getByText("仍可回查的原文")).toBeVisible();
  expect(get).toHaveBeenCalledWith("p", "n");
});
