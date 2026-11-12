import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import type { ChapterNote, NoteRelation } from "@/types/novel-workflow";
import { ReadingQuestions, RelationDescription } from "./ReadingAnnotations";

const relation: NoteRelation = { id: "r", subject: "阳子", target: "父亲", relation: "女儿", previous: "未明确", trigger: "未明确", story_time: "现在", evidence: { note_id: "n", source_file: "book", start: 0, end: 2, quote: "原文" } };
it("does not turn an unrecorded prior relationship into a story change", () => {
  render(<RelationDescription relation={relation} />);
  expect(screen.getByText("阳子是父亲的女儿")).toBeInTheDocument();
  expect(screen.queryByText(/未明确 →/)).not.toBeInTheDocument();
  expect(screen.getByText(/不代表此时发生关系变化/)).toBeInTheDocument();
  expect(screen.queryByText("现在")).not.toBeInTheDocument();
});
it("preserves an evidenced real relationship change", () => {
  render(<RelationDescription relation={{ ...relation, previous: "陌生人", relation: "同伴", record_kind: "changed", trigger: "共同脱险" }} />);
  expect(screen.getByText("关系变化：陌生人 → 同伴")).toBeInTheDocument();
  expect(screen.getByText("共同脱险")).toBeInTheDocument();
});
it("deduplicates reading questions and leaves old questions unclassified", () => {
  const reading: NonNullable<ChapterNote["reading"]> = { basis: "b", summaries: [], assets: [], changes: [], events: [], questions: ["为什么被追？", "指代是谁？"], reading_questions: [{ text: "为什么被追？", kind: "plot_unrevealed" }, { text: "指代是谁？", kind: "extraction_check" }, { text: "旧记录", kind: "unclassified" }] };
  render(<ReadingQuestions reading={reading} />);
  expect(screen.getAllByText("为什么被追？")).toHaveLength(1);
  expect(screen.getByText("剧情待揭示")).toBeInTheDocument();
  expect(screen.getByText("抽取待核实")).toBeInTheDocument();
  expect(screen.getByText("尚未分类")).toBeInTheDocument();
});

it("hides bare family and school roles but keeps changes and identity revelations", async () => {
  const { storyRelations } = await import("./ReadingAnnotations");
  const teacher = { ...relation, id: "teacher", subject: "女老师", target: "阳子", relation: "老师" };
  const loyalty = { ...relation, id: "loyalty", relation: "效忠者" };
  const adoption = { ...relation, id: "adoption", record_kind: "established" as const };
  const change = { ...teacher, id: "change", previous: "陌生人", record_kind: "changed" as const };
  expect(storyRelations([relation, teacher, loyalty, adoption, change]).map((r) => r.id)).toEqual(["loyalty", "adoption", "change"]);
});
