import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { API } from "@/api";
import { RulesPage } from "./RulesPage";
afterEach(() => vi.restoreAllMocks());
it("shows the effective project rule and lets staff search production prompts without editing", async () => {
  vi.spyOn(API, "getWorkbenchRules").mockResolvedValue({ read_only: true, entries: [
    { id: "novel/svt", title: "主归属与备选", purpose: "一章一 Note", category: "novel", source: "project", location: "novel_workflow/rules/svt.md", version: "abc", content: "每个 Note 仅一个主归属，另有多个备选。" },
    { id: "template/video", title: "视频规则", purpose: "视频", category: "production", source: "default", location: "video.md", version: "def", content: "镜头保持连续。" },
  ] });
  render(<RulesPage projectName="book" />);
  expect(await screen.findByText("每个 Note 仅一个主归属，另有多个备选。")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存" })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "全部" }));
  fireEvent.change(screen.getByRole("textbox", { name: "搜索规则、提示词或关键词" }), { target: { value: "连续" } });
  expect(screen.getByText("镜头保持连续。")).toBeInTheDocument();
});
