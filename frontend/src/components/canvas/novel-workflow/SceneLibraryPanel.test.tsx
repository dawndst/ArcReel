import { useState } from "react";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { SceneLibraryBatch } from "@/types/novel-workflow";
import { SceneLibraryPanel } from "./SceneLibraryPanel";
import { NoteGroupsPanel } from "./NoteGroupsPanel";

const batch: SceneLibraryBatch = { basis: "b", note_id: "n", stale: false, skipped_reason: "", scenes: [{ id: "SCN-1", title: "门前", location: "门口", time: "白天", purpose: "冲突", shots: [1, 2].map((i) => ({ id: `SH-${i}`, title: `镜头${i}`, evidence: { note_id: "n", source_file: "book", start: 0, end: 2, quote: "原文" }, segments: Array.from({ length: i }, () => ({ duration_seconds: 8, scene_description: "动作", characters_in_scene: [], scenes: [], props: [], utterances: [] })) })) }] };
it("selects a whole scene, orders logical shots, and keeps SEG together", () => {
  const assemble = vi.fn();
  function Host() { const [ids, setIds] = useState<string[]>([]); const [title, setTitle] = useState(""); return <SceneLibraryPanel batches={[batch]} notes={[]} disabled={false} selection={ids} setSelection={setIds} title={title} setTitle={setTitle} assemble={() => assemble(ids, title)} source={() => {}} />; }
  render(<Host />);
  fireEvent.click(screen.getByRole("checkbox", { name: "选择整场：门前" }));
  expect(screen.getByText("已选 2 镜 · 约 24 秒")).toBeInTheDocument();
  expect(screen.getByText("SEG1 · 8s")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "上移第 2 个镜头" }));
  fireEvent.change(screen.getByRole("textbox", { name: "成片集标题" }), { target: { value: "追逐" } });
  fireEvent.click(screen.getByRole("button", { name: "将所选场镜编排为一集" }));
  expect(assemble).toHaveBeenCalledWith(["SH-2", "SH-1"], "追逐");
});
it("cannot assemble stale selected shots", () => {
  render(<SceneLibraryPanel batches={[{ ...batch, stale: true }]} notes={[]} disabled={false} selection={["SH-1"]} setSelection={() => {}} title="集" setTitle={() => {}} assemble={() => {}} source={() => {}} />);
  expect(screen.getByRole("button", { name: "将所选场镜编排为一集" })).toBeDisabled();
});
it("management groups expose synopsis and reference controls, never episode assembly", () => {
  const usage = vi.fn();
  render(<NoteGroupsPanel groups={[{ id: "g", title: "闲杂资料", note_ids: ["n"], source_basis: "b", created_by: "human" }]} notes={[]} disabled={false} select={() => {}} summarize={() => {}} usage={usage} dissolve={() => {}} />);
  const card = screen.getByRole("article");
  expect(within(card).queryByText("据此编排一集")).not.toBeInTheDocument();
  fireEvent.click(within(card).getByRole("button", { name: "设为仅留档" }));
  expect(usage).toHaveBeenCalledOnce();
});
it("keeps unresolved dialogue visible and requires attribution before assembly", () => {
  const draft = structuredClone(batch);
  const shot = draft.scenes[0].shots[0];
  shot.revision = "rev";
  shot.segments[0].utterances = [{ kind: "dialogue", speaker: null, text: "不愧是班长。" }];
  const attribute = vi.fn();
  render(<SceneLibraryPanel batches={[draft]} notes={[]} disabled={false} selection={[shot.id]} setSelection={() => {}} title="验收" setTitle={() => {}} assemble={() => {}} source={() => {}} characters={["同学甲"]} attribute={attribute} />);
  expect(screen.getByText("说话人待确认：不愧是班长。")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "将所选场镜编排为一集" })).toBeDisabled();
  fireEvent.change(screen.getByRole("combobox", { name: "确认说话人" }), { target: { value: "同学甲" } });
  expect(attribute).toHaveBeenCalledWith(shot.id, 0, 0, "同学甲", "rev");
});
it("shows before/after changes and blocks only selected unadopted revisions", () => {
  const draft = structuredClone(batch);
  draft.review = { revisions: [{ id: "r", scene_index: 0, shot_index: 0, segment_index: null, field: "title", before: "红发", after: "发辫", reason: "发色未明确", source_quote: "编成一条辫子", applied: false }], unresolved: [] };
  const adopt = vi.fn();
  render(<SceneLibraryPanel batches={[draft]} notes={[]} disabled={false} selection={["SH-1"]} setSelection={() => {}} title="验收" setTitle={() => {}} assemble={() => {}} source={() => {}} adoptRevision={adopt} />);
  expect(screen.getByText("红发").closest("p")).toHaveClass("bg-destructive/10");
  expect(screen.getByText("发辫")).toHaveClass("bg-primary/10");
  expect(screen.getByRole("button", { name: "将所选场镜编排为一集" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "采用修订并保存新版本" }));
  expect(adopt).toHaveBeenCalledWith("b", "r");
});

it("numbers recovered batches in source order and keeps stable IDs for selection and filtering", () => {
  const first = structuredClone(batch);
  first.part = 0;
  first.basis = "first";
  first.scenes[0].id = "SCN-0007";
  first.scenes[0].shots[0].id = "SH-0030";
  first.scenes[0].shots[1].id = "SH-0031";
  const second = structuredClone(batch);
  second.part = 1;
  second.basis = "second";
  second.scenes[0].id = "SCN-0005";
  second.scenes[0].title = "办公室";
  second.scenes[0].shots = [{ ...second.scenes[0].shots[0], id: "SH-0018", title: "来袭" }];
  const select = vi.fn();
  render(<SceneLibraryPanel batches={[second, first]} notes={[]} disabled={false} selection={[]} setSelection={select} title="" setTitle={() => {}} assemble={() => {}} source={() => {}} />);
  expect(screen.getAllByRole("article").map((card) => within(card).getAllByRole("checkbox")[0].getAttribute("aria-label"))).toEqual(["选择整场：门前", "选择整场：办公室"]);
  expect(screen.getByText("SCN-001 · SH-001")).toBeInTheDocument();
  expect(screen.getByText("SCN-002 · SH-003")).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: "搜索场、镜头或对白" }), { target: { value: "SH-003" } });
  expect(screen.queryByText("SCN-001 · SH-001")).not.toBeInTheDocument();
  expect(screen.getByText("SCN-002 · SH-003")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("checkbox", { name: "选择镜头：来袭" }));
  expect(select).toHaveBeenCalledWith(["SH-0018"]);
});
