import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { API } from "@/api";
import { EpisodeGuideDetails } from "./EpisodeGuideDetails";

beforeEach(() => vi.restoreAllMocks());
it("generates a complete guide and replaces old beats with all five sections", async () => {
  vi.spyOn(API, "getEpisodeGuide").mockResolvedValue({ guide: null, stale: false, source_range: null });
  vi.spyOn(API, "generateEpisodeGuide").mockResolvedValue({ stale: false, source_range: null, guide: {
    summary: "主角为自保而应对冲突，最终离开。", story_beats: ["冲突升级"], character_changes: ["由信任变为怀疑"],
    adaptation_value: "人物首次主动选择", recommendation: "compress", recommendation_reason: "保留选择，缩短重复说明", ending_hook: "去向尚未揭示",
  } });
  render(<EpisodeGuideDetails projectName="demo" episode={1} revision={0} fallback={<p>旧节点</p>} />);
  const button = screen.getByRole("button", { name: "生成完整导览" });
  await waitFor(() => expect(button).toBeEnabled());
  fireEvent.click(button);
  expect(await screen.findByText("主角为自保而应对冲突，最终离开。")).toBeInTheDocument();
  expect(screen.getByText("由信任变为怀疑")).toBeInTheDocument();
  expect(screen.getByText("建议压缩")).toBeInTheDocument();
  expect(screen.getByText("去向尚未揭示")).toBeInTheDocument();
  expect(screen.queryByText("旧节点")).not.toBeInTheDocument();
});
it("hides stale guide and offers regeneration", async () => {
  vi.spyOn(API, "getEpisodeGuide").mockResolvedValue({ guide: null, stale: true, source_range: null });
  render(<EpisodeGuideDetails projectName="demo" episode={1} revision={0} />);
  expect(await screen.findByText("本集原文或导览规则已变化，请重新生成。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "生成完整导览" })).toBeEnabled();
});
