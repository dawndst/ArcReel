import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ShotRhythmStrip, shotScale } from "./ShotRhythmStrip";
import type { LibraryShot } from "@/types/novel-workflow";

it("uses the given edit order, keeps SEG within its shot, and locates without changing selection", () => {
  const shot = (id: string, durations: number[]): LibraryShot => ({ id, title: id, evidence: { note_id: "n", source_file: "s", start: 0, end: 1, quote: "原" }, segments: durations.map((duration_seconds) => ({ duration_seconds, scene_description: "画面", characters_in_scene: [], scenes: [], props: [], utterances: [] })) });
  const locate = vi.fn();
  render(<ShotRhythmStrip shots={[shot("b", [8, 7]), shot("a", [5])]} labels={new Map([["a", "SH-001"], ["b", "SH-002"]])} locate={locate} />);
  const bars = within(screen.getByRole("region", { name: "分镜节奏条" })).getAllByRole("button");
  expect(bars).toHaveLength(2);
  expect(bars[0]).toHaveAccessibleName(/SH-002.*15s/);
  expect(bars[0]).toHaveStyle({ "--shot-duration": "15" });
  expect(bars[1]).toHaveStyle({ "--shot-duration": "5" });
  fireEvent.click(bars[1]!);
  expect(locate).toHaveBeenCalledWith("a");
  expect(bars[1]).toHaveAttribute("aria-current", "true");
});

it("does not invent a category for mixed or unknown framing", () => {
  expect(shotScale("中近景")).toBe(3);
  expect(shotScale("大特写")).toBe(6);
  expect(shotScale("近景切全景")).toBe(0);
  expect(shotScale("")).toBe(0);
});
