import { render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { API } from "@/api";
import { NovelReadingProgress } from "./NovelReadingProgress";

afterEach(() => vi.restoreAllMocks());
it("shows the reading stage during a script task", async () => {
  vi.spyOn(API, "getNovelUnderstanding").mockResolvedValue({enabled: true, phase: "reading", coverage: 12.5, completed_chunks: 9, total_chunks: 78, reports: []});
  const { rerender } = render(<NovelReadingProgress projectName="demo" active />);
  expect(await screen.findByRole("status")).toHaveTextContent("正在分批阅读 · 12.5%");
  rerender(<NovelReadingProgress projectName="demo" active={false} />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});
it("does not fetch when no text task is active", () => {
  const fetch = vi.spyOn(API, "getNovelUnderstanding");
  render(<NovelReadingProgress projectName="demo" active={false} />);
  expect(fetch).not.toHaveBeenCalled();
});

it("shows scene generation as its actual stage instead of hiding it", async () => {
  vi.spyOn(API, "getNovelWorkflow").mockResolvedValue({ initialized: true, notes: [], groups: [], svts: [], stale: false, progress: { phase: "scenes", done: 1, total: 2 } });
  render(<NovelReadingProgress projectName="demo" active notebook />);
  expect(await screen.findByRole("status")).toHaveTextContent("生成场与镜头 · 50%");
});
