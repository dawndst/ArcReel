import { render, screen, fireEvent, waitFor, within } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useTasksStore } from "@/stores/tasks-store";
import type { NovelWorkflow } from "@/types/novel-workflow";
import { NovelWorkbench } from "./NovelWorkbench";

const data: NovelWorkflow = {
  initialized: true, source_basis: "source-version", stale: false, groups: [], svts: [], progress: null,
  notes: [1, 2].map((i) => ({ id: `note-${i}`, order: i, title: `卷一 · 第${i}章`, volume: "卷一", chapter: `第${i}章`, chars: 100, basis: `basis-${i}`, status: "unread", sections: [{ title: `第${i}章`, source_file: "source/book.txt", start: i * 100, end: (i + 1) * 100 }] })),
};
beforeEach(() => {
  vi.restoreAllMocks();
  useTasksStore.setState(useTasksStore.getInitialState(), true);
  vi.spyOn(useTasksStore.getState(), "refreshTasks").mockResolvedValue(undefined);
  vi.spyOn(API, "getNovelWorkflow").mockResolvedValue(data);
});
it("opens chapter Notes without starting reading or merging and shows unread state", async () => {
  const run = vi.spyOn(API, "runNoteWorkflow");
  const merge = vi.spyOn(API, "createNoteGroup");
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  expect(await screen.findByRole("heading", { name: "卷一 · 第1章" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "从所选 Note 提炼 SVT" })).toBeDisabled();
  expect(screen.getByText(/尚未完成精读/)).toBeInTheDocument();
  expect(run).not.toHaveBeenCalled();
  expect(merge).not.toHaveBeenCalled();
});
it("requires human confirmation to group selected Notes and preserves source Notes", async () => {
  const merged = { id: "group-1", title: "改编组合", note_ids: ["note-1", "note-2"], source_basis: data.source_basis!, created_by: "human" };
  const merge = vi.spyOn(API, "createNoteGroup").mockImplementation(async () => {
    vi.mocked(API.getNovelWorkflow).mockResolvedValue({ ...data, groups: [merged] });
    return merged;
  });
  render(<NovelWorkbench projectName="demo" onProduction={() => {}} />);
  fireEvent.click(await screen.findByRole("checkbox", { name: "选择 卷一 · 第1章" }));
  fireEvent.click(screen.getByRole("checkbox", { name: "选择 卷一 · 第2章" }));
  fireEvent.click(screen.getByRole("button", { name: "人工合并 Note" }));
  expect(merge).not.toHaveBeenCalled();
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("卷一 · 第1章")).toBeInTheDocument();
  fireEvent.change(within(dialog).getByRole("textbox"), { target: { value: "改编组合" } });
  fireEvent.click(within(dialog).getByRole("button", { name: "确认创建组合" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(await screen.findByRole("heading", { name: "改编组合" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "章节 Note (2)" })).toBeInTheDocument();
});
