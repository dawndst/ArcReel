import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ChapterNote } from "@/types/novel-workflow";
import { ReadingScopePanel } from "./ReadingScopePanel";

it("selects a chapter interval without triggering reading and saves scope explicitly", () => {
  const select = vi.fn(); const save = vi.fn();
  const notes = [1, 2, 3, 4].map((i) => ({ id: `n${i}`, title: `第${i}章` })) as ChapterNote[];
  render(<ReadingScopePanel notes={notes} scope={undefined} selected={["n1"]} disabled={false} select={select} save={save} />);
  fireEvent.change(screen.getByLabelText("起始章节序号"), { target: { value: "2" } });
  fireEvent.click(screen.getByRole("button", { name: "选择此范围" }));
  expect(select).toHaveBeenCalledWith(["n2", "n3"]);
  expect(save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "以所选章节设定可用范围" }));
  expect(save).toHaveBeenCalledOnce();
  fireEvent.change(screen.getByLabelText("结束章节序号"), { target: { value: "1" } });
  expect(screen.getByRole("button", { name: "选择此范围" })).toBeDisabled();
});
