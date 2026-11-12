import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { API } from "@/api";
import { SceneBatchSource } from "./SceneBatchSource";

it("opens the actual batch source without navigating to a collapsed Note", async () => {
  const get = vi.spyOn(API, "getSceneBatchSource").mockResolvedValue({ text: "当前片段准确原文", source_file: "book", start: 100, end: 108, note_title: "第一章", part: 2, shots: [] });
  render(<SceneBatchSource projectName="p" basis="batch" close={() => {}} />);
  expect(await screen.findByText("当前片段准确原文")).toBeInTheDocument();
  expect(get).toHaveBeenCalledWith("p", "batch");
  expect(screen.getByText("book · 100–108")).toBeInTheDocument();
});
