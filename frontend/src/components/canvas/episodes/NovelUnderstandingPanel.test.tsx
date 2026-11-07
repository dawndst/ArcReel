import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { API } from "@/api";
import { useProjectsStore } from "@/stores/projects-store";
import type { NovelStatus } from "@/types/novel-understanding";
import { NovelUnderstandingPanel } from "./NovelUnderstandingPanel";
const status: NovelStatus = {
  enabled: true, phase: "ready", coverage: 100, completed_chunks: 2, total_chunks: 2,
  reports: [{ id: "report", episode: 1, next_episode: 2, decision: {
    action: "merge_next", title: "新的开端", reason: "重复铺垫可合并", must_film: ["离开故乡"],
    compress: ["赶路"], omit: [], preserve_setup: ["旧信"], story_beats: ["出发", "到达"], hook: "门后是谁",
  }, evidence: [{ source_file: "source/book.txt", start: 0, end: 10, quote: "他把旧信藏进衣袖，转身离开。" }] }],
};
describe("NovelUnderstandingPanel", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useProjectsStore.setState(useProjectsStore.getInitialState(), true);
    vi.spyOn(API, "getNovelUnderstanding").mockResolvedValue(status);
    vi.spyOn(API, "getProject").mockResolvedValue({project: { title: "Demo", content_mode: "drama", style: "", episodes: [], characters: {} }, scripts: {}});
  });
  it("keeps disabled projects out of model calls", async () => {
    vi.spyOn(API, "getNovelUnderstanding").mockResolvedValue({...status, enabled: false, reports: []});
    const review = vi.spyOn(API, "reviewNovelUnderstanding");
    render(<NovelUnderstandingPanel projectName="demo" planning={false} onChanged={() => {}} />);
    const button = await screen.findByRole("button", {name: "建立资料 / 审查大纲"});
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(review).not.toHaveBeenCalled();
  });
  it("previews impact before adopting a merge and refreshes after writing", async () => {
    const changed = vi.fn();
    const adopt = vi.spyOn(API, "adoptNovelDecision")
      .mockResolvedValueOnce({ status: "confirmation_required", impact: { restaled: [1], retired: [2], removed: [], merged_units: 3, text: "已有产物需要更新" } })
      .mockResolvedValueOnce({ status: "applied" });
    render(<NovelUnderstandingPanel projectName="demo" planning={false} onChanged={changed} />);
    await screen.findByText("100%", { exact: false });
    fireEvent.click(screen.getByText("改编建议（1）"));
    fireEvent.click(screen.getByRole("button", {name: "预览并采纳"}));
    const dialog = await screen.findByRole("dialog");
    expect(adopt).toHaveBeenCalledTimes(1);
    expect(dialog).toHaveTextContent("已有产物需要更新");
    fireEvent.click(within(dialog).getByRole("button", {name: "确认"}));
    await waitFor(() => expect(changed).toHaveBeenCalledOnce());
    expect(adopt).toHaveBeenLastCalledWith("demo", { report_id: "report", dry_run: false, confirm_episodes: [1, 2], confirm_merged_units: 3 });
  });
});
