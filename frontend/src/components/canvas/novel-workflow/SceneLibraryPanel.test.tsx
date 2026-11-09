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
