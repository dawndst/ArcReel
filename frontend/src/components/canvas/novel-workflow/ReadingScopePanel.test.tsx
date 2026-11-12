import { expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ReadingScopePanel } from "./ReadingScopePanel";
import type { ChapterNote } from "@/types/novel-workflow";

it("adds chapters by default and previews a scope restriction without hiding saved Notes", () => {
  const notes: ChapterNote[] = [1, 2].map((n) => ({ id: `n${n}`, order: n, title: `第${n}章`, volume: "", chapter: "", chars: 100, basis: "b", sections: [], status: "read" }));
  const save = vi.fn();
  render(<ReadingScopePanel scope={{ configured: true, note_ids: ["n1", "n2"], available_count: 2, read_count: 2, total_count: 2, mode: "ongoing" }} notes={notes} selected={["n2"]} disabled={false} save={save} />);
  expect(save).not.toHaveBeenCalled();
  expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText(/制作与检索范围/));
  fireEvent.click(screen.getByRole("button", { name: "追加输入章节（保留现有范围）" }));
  expect(save).toHaveBeenLastCalledWith(true);
  fireEvent.click(screen.getByRole("button", { name: "将可用范围限定为输入章节…" }));
  expect(save).toHaveBeenCalledTimes(1);
  expect(screen.getByText(/1 章将暂不参与制作与检索/)).toBeVisible();
  expect(screen.getByText(/已生成的 Note、精简稿和素材不会删除/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "确认限定范围，保留已有 Note" }));
  expect(save).toHaveBeenLastCalledWith(false);
});
