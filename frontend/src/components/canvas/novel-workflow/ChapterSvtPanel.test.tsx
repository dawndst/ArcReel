import { fireEvent, render, screen, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ChapterNote, ChapterSVTStory, NovelSVT, SVTMoment } from "@/types/novel-workflow";
import { ChapterSvtPanel } from "./ChapterSvtPanel";

const notes: ChapterNote[] = [1, 2].map((i) => ({ id: `n${i}`, title: `第${i}章`, order: i, volume: "卷一", chapter: `第${i}章`, chars: 100, basis: `r${i}`, sections: [] }));
const stories: Record<string, ChapterSVTStory> = Object.fromEntries(notes.map((n) => [n.id, { note_id: n.id, title: `${n.title}独立剧情`, summary: `${n.title}的触发行动和转折`, advancement: `${n.title}发生的变化`, event_ids: [`e${n.id}`], basis: "v", reading_basis: n.basis, rule_basis: "rule" }]));
function moment(noteId: string): SVTMoment {
  const evidence = { note_id: noteId, source_file: "book", start: 0, end: 2, quote: `${noteId}原句` };
  return { scene: `${noteId}爆点场面`, reason: "转折", note_ids: [noteId], dialogue_ids: [`d${noteId}`], dialogues: [{ id: `d${noteId}`, speaker: "阳子", quote: `${noteId}台词`, value: "关键", evidence }], evidence: [evidence] };
}
const svt: NovelSVT = { id: "mainline", title: "共享主线", summary: "两章累计背景", mainline_reason: "因果关联", status: "open", note_ids: ["n1", "n2"], note_stories: stories, climaxes: [moment("n1"), moment("n2")], payoffs: [], dialogues: [], evidence: [] };

it("prioritizes the selected chapter story and dialogue while collapsing shared background", () => {
  const { rerender } = render(<ChapterSvtPanel notes={notes} svts={[svt]} noteId="n2" select={vi.fn()} sources={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "第2章独立剧情" })).toBeVisible();
  expect(screen.getByText("第2章的触发行动和转折")).toBeVisible();
  expect(screen.getByText("n2台词")).toBeVisible();
  expect(screen.queryByText("n1台词")).not.toBeInTheDocument();
  const background = screen.getByText(/关联主线与跨章概况 · 共享主线/).closest("details")!;
  expect(background).not.toHaveAttribute("open");
  expect(within(background).getByText("两章累计背景")).not.toBeVisible();
  rerender(<ChapterSvtPanel notes={notes} svts={[svt]} noteId="n1" select={vi.fn()} sources={vi.fn()} />);
  expect(screen.getByRole("heading", { name: "第1章独立剧情" })).toBeVisible();
  expect(screen.queryByText("n2台词")).not.toBeInTheDocument();
});

it("lets staff switch chapter and limits mixed-climax dialogue to that chapter", () => {
  const select = vi.fn();
  const mixed = { ...moment("n1"), note_ids: ["n1", "n2"], dialogues: [...moment("n1").dialogues, ...moment("n2").dialogues] };
  render(<ChapterSvtPanel notes={notes} svts={[{ ...svt, climaxes: [mixed] }]} noteId="n2" select={select} sources={vi.fn()} />);
  fireEvent.change(screen.getByRole("combobox", { name: "SVT 来源章节" }), { target: { value: "n1" } });
  expect(select).toHaveBeenCalledWith("n1");
  expect(screen.getAllByText("跨章爆点 · 台词仅列本章来源")[0]).toBeVisible();
  expect(screen.queryByText("n1爆点场面")).not.toBeInTheDocument();
  expect(screen.getByText("n2台词")).toBeVisible();
  expect(screen.queryByText("n1台词")).not.toBeInTheDocument();
});
