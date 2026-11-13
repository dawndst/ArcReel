import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SceneLibraryBatch } from "@/types/novel-workflow";
import { DialogueCoveragePanel } from "./DialogueCoveragePanel";
import { SceneQuestions } from "./SceneQuestions";

const batch: SceneLibraryBatch = { basis: "batch", note_id: "note", stale: false, skipped_reason: "", scenes: [], review_revision: "review", review: { revisions: [], unresolved: ["问答已补回"] }, dialogue_coverage: { revision: "coverage", counts: { retained: 0, partial: 1, unassigned: 0, omitted: 1 }, entries: [{ dialogue_id: "d", quote: "为何你知道？", speaker: "阳子", purposes: ["因果"], status: "partial", locations: [{ shot_id: "SH-0074", segment_index: 0, utterance_index: 1 }] }, { dialogue_id: "omitted", quote: "略去的对白", speaker: "猴子", purposes: [], status: "omitted", reason: "已有画面表达这层含义", locations: [] }] } };

it("distinguishes partial coverage from intentional omission and requires a versioned reason", () => {
  const decide = vi.fn(); const locate = vi.fn();
  render(<DialogueCoveragePanel batch={batch} disabled={false} decide={decide} locate={locate} />);
  expect(screen.getByText("未完整保留 · 阳子")).toBeInTheDocument();
  expect(screen.getByText("已人工省略 · 猴子")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "SH-0074 · SEG1 · 第2句" }));
  expect(locate).toHaveBeenCalledWith("SH-0074");
  fireEvent.click(screen.getByRole("button", { name: "注明人工省略" }));
  expect(screen.getByRole("button", { name: "保存处理决定" })).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: "处理理由" }), { target: { value: "通过可见动作表达相同因果" } });
  fireEvent.click(screen.getByRole("button", { name: "保存处理决定" }));
  expect(decide).toHaveBeenCalledWith("batch", "coverage", "d", "omit", "通过可见动作表达相同因果");
  fireEvent.click(screen.getByRole("button", { name: "恢复安排" }));
  fireEvent.change(screen.getByRole("textbox", { name: "处理理由" }), { target: { value: "此句是下一场成立的必要前提" } });
  fireEvent.click(screen.getByRole("button", { name: "保存处理决定" }));
  expect(decide).toHaveBeenLastCalledWith("batch", "coverage", "omitted", "restore", "此句是下一场成立的必要前提");
});

it("allows resolving one repaired question while another shot still has an anonymous speaker", () => {
  const draft = structuredClone(batch); const confirm = vi.fn();
  draft.scenes = [{ id: "s", title: "街上", location: "街上", time: "白天", purpose: "群众声", shots: [{ id: "SH-1", title: "群众", evidence: { note_id: "note", source_file: "book", start: 0, end: 1, quote: "喊声" }, segments: [{ duration_seconds: 5, scene_description: "画外喊声", characters_in_scene: [], scenes: [], props: [], utterances: [{ kind: "dialogue", speaker: null, text: "快逃", delivery: "off_screen" }] }] }] }];
  render(<SceneQuestions batch={draft} disabled={false} confirm={confirm} locate={() => {}} source={() => {}} shotLabels={new Map()} />);
  fireEvent.click(screen.getByRole("button", { name: "已完成修复" }));
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "此处问答已依据本段原文补回" } });
  fireEvent.click(screen.getByRole("button", { name: "确认这一项" }));
  expect(confirm).toHaveBeenCalledWith("batch", "review", "此处问答已依据本段原文补回", 0, "repaired");
});

it("does not offer omission for a fully retained line", () => {
  const draft = structuredClone(batch);
  draft.dialogue_coverage!.entries = [{ dialogue_id: "kept", quote: "完整保留的原句", speaker: "阳子", purposes: [], status: "retained", locations: [{ shot_id: "SH-1", segment_index: 0, utterance_index: 0 }] }];
  draft.dialogue_coverage!.counts = { retained: 1, partial: 0, unassigned: 0, omitted: 0 };
  render(<DialogueCoveragePanel batch={draft} disabled={false} decide={vi.fn()} locate={() => {}} />);
  expect(screen.getByText("已完整保留 · 阳子")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "注明人工省略" })).not.toBeInTheDocument();
});
