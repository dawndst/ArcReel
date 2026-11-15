import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { NoteReadAction } from "./NoteReadAction";
import type { ChapterNote } from "@/types/novel-workflow";

const note = { id: "n", title: "第二章", status: "read" } as ChapterNote;
it("requires confirmation before resuming an existing Note and cancellation submits nothing", async () => {
  const run = vi.fn().mockResolvedValue(undefined);
  render(<NoteReadAction notes={[note]} disabled={false} run={run} />);
  fireEvent.click(screen.getByRole("button", { name: /Note 已生成/ }));
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(run).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "取消" }));
  expect(run).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /Note 已生成/ }));
  fireEvent.click(screen.getByRole("button", { name: "确认检查并续跑" }));
  await waitFor(() => expect(run).toHaveBeenCalledExactlyOnceWith(["n"]));
});
it("blocks confirmation when the selection changes", () => {
  const run = vi.fn();
  const { rerender } = render(<NoteReadAction notes={[note]} disabled={false} run={run} />);
  fireEvent.click(screen.getByRole("button", { name: /Note 已生成/ }));
  rerender(<NoteReadAction notes={[{ ...note, id: "other" }]} disabled={false} run={run} />);
  expect(screen.getByRole("button", { name: "确认检查并续跑" })).toBeDisabled();
  expect(run).not.toHaveBeenCalled();
});
