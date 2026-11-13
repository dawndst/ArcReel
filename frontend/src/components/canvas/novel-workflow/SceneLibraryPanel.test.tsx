import { LeaveGuardProvider } from "@/components/shared/edit-unit/LeaveGuard";
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
  expect(screen.getByText("不愧是班长。").closest("p")).toHaveTextContent("说话人待确认：不愧是班长。");
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

it("shows linked moments, registered assets, design and dialogue coverage together", () => {
  const draft = structuredClone(batch);
  const shot = draft.scenes[0].shots[0];
  const design = { purpose: "建立压迫", shot_size: "近景", camera_angle: "平视", camera_movement: "固定", framing: "阳子在画面右侧", continuity: "保持视线方向", sound: "只保留环境声" };
  draft.production_context = { svt_id: "svt", events: [], moments: [{ id: "moment", kind: "climaxes", svt_id: "svt", note_ids: ["n"], event_ids: ["event"], partial: false, scene: "拒绝同行", reason: "冲突升级", dialogues: [{ id: "line", speaker: "阳子", quote: "不要", value: "拒绝", evidence: shot.evidence }] }] };
  shot.production = { shot_id: shot.id, event_ids: ["event"], moment_ids: ["moment"], design, svt_id: "svt", assets: [{ kind: "character", name: "阳子", asset_code: "CHR-001", asset_id: "asset", variant: "人形", segments: [0], missing: false }], dialogue_sources: [{ segment: 0, utterance: 0, dialogue_id: "line" }] };
  const openAsset = vi.fn();
  render(<SceneLibraryPanel batches={[draft]} notes={[]} disabled={false} selection={[shot.id]} setSelection={() => {}} title="" setTitle={() => {}} assemble={() => {}} source={() => {}} openAsset={openAsset} />);
  expect(screen.getByText("近景 · 平视 · 固定")).toBeInTheDocument();
  expect(screen.getByText("关联 1 镜 · 关键台词 1 / 1")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "CHR-001 · 阳子 / 人形" }));
  expect(openAsset).toHaveBeenCalledWith(shot.production.assets[0]);
});

it("offers completion without regenerating selection and blocks missing production details", () => {
  const draft = structuredClone(batch);
  draft.scenes[0].shots[0].issues = [{ code: "design", blocking: true }];
  const complete = vi.fn();
  render(<SceneLibraryPanel batches={[draft]} notes={[]} disabled={false} selection={["SH-1"]} setSelection={() => {}} title="第一集" setTitle={() => {}} assemble={() => {}} source={() => {}} completeProduction={complete} />);
  expect(screen.getByRole("button", { name: "将所选场镜编排为一集" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "完善素材制作信息" }));
  expect(complete).toHaveBeenCalledWith(["n"]);
});


it("opens an accessible design editor without marking untouched fields dirty", () => {
  const draft = structuredClone(batch);
  const shot = draft.scenes[0].shots[0];
  shot.revision = "revision";
  const design = { purpose: "建立压迫", shot_size: "近景", camera_angle: "平视", camera_movement: "固定", framing: "右侧", continuity: "保持视线", sound: "环境声" };
  draft.production_context = { svt_id: "svt", events: [], moments: [] };
  shot.production = { shot_id: shot.id, event_ids: [], moment_ids: [], design, svt_id: "svt", assets: [], dialogue_sources: [] };
  render(<LeaveGuardProvider><SceneLibraryPanel batches={[draft]} notes={[]} disabled={false} selection={[]} setSelection={() => {}} title="" setTitle={() => {}} assemble={() => {}} source={() => {}} saveProduction={async () => {}} /></LeaveGuardProvider>);
  fireEvent.click(screen.getByText("镜头设计 · 改编决定"));
  fireEvent.click(screen.getByRole("button", { name: "编辑镜头设计与关联" }));
  expect(screen.getByRole("textbox", { name: "镜头目的" })).toHaveValue("建立压迫");
  expect(screen.getByRole("textbox", { name: "景别" })).toHaveValue("近景");
  fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "取消" }));
});

it("resolves one review question without hiding missing speakers", () => {
  const draft = structuredClone(batch);
  draft.review_revision = "review-v1";
  draft.review = { revisions: [], unresolved: ["utterances 缺少归属", "动作需要核对"] };
  draft.scenes[0]!.shots[0]!.segments[0]!.utterances = [{ kind: "dialogue", speaker: null, text: "谁？" }];
  const confirm = vi.fn();
  render(<SceneLibraryPanel batches={[draft]} notes={[]} disabled={false} selection={[]} setSelection={() => {}} title="" setTitle={() => {}} assemble={() => {}} source={() => {}} confirmQuestions={confirm} />);
  fireEvent.click(screen.getByText("原文一致性检查 (2)"));
  expect(screen.getByText("1. 台词 缺少归属")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: "已完成修复" })[0]).toBeEnabled();
  fireEvent.click(screen.getAllByRole("button", { name: "这是误报" })[1]!);
  fireEvent.change(screen.getByRole("textbox", { name: "说明为什么是误报，并引用原文依据（至少10字）" }), { target: { value: "动作与原文描写完全一致，此项为误报" } });
  fireEvent.click(screen.getByRole("button", { name: "确认这一项" }));
  expect(confirm).toHaveBeenCalledWith("b", "review-v1", "动作与原文描写完全一致，此项为误报", 1, "false_positive");
  expect(screen.getByText(/谁/).closest("p")).toHaveTextContent(/说话人待确认：.*谁/);
});

it("renders dialogue-array revisions as readable speaker lines", () => {
  const draft = structuredClone(batch);
  draft.review = { revisions: [{ id: "dialogue-r", scene_index: 0, shot_index: 0, segment_index: 0, field: "utterances", before: [{ kind: "dialogue", speaker: "阳子", text: "为什么？", delivery: "on_screen" }], after: [{ kind: "dialogue", speaker: "猴子", text: "我知道。", delivery: "on_screen" }, { kind: "dialogue", speaker: "阳子", text: "为什么？", delivery: "on_screen" }], reason: "补齐问答前提", source_quote: "我知道。为什么？", applied: false }], unresolved: [] };
  render(<SceneLibraryPanel batches={[draft]} notes={[]} disabled={false} selection={[]} setSelection={() => {}} title="" setTitle={() => {}} assemble={() => {}} source={() => {}} />);
  expect(screen.getAllByText(/阳子 · 画内对白：为什么？/).length).toBeGreaterThan(0);
  expect(screen.getByText(/猴子 · 画内对白：我知道。/)).toBeInTheDocument();
  expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
});
