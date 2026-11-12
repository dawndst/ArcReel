import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { API } from "@/api";
import type { DeliveryPlan, LibraryShot, ShotEdit } from "@/types/novel-workflow";
import { DeliveryPanel } from "./DeliveryPanel";
import { ExecutionEditor } from "./ExecutionEditor";

const shot: LibraryShot = { id: "SH-1", title: "出发", revision: "r", evidence: { note_id: "n", source_file: "source/book.txt", start: 0, end: 8, quote: "甲说：出发。" }, segments: [{ duration_seconds: 8, scene_description: "甲拿起剑", characters_in_scene: [], scenes: [], props: [], utterances: [{ kind: "dialogue", speaker: "甲", text: "出发。", delivery: "unclassified" }] }] };
const initial: DeliveryPlan = { basis: "basis", title: "出发", shot_ids: ["SH-1"], note_ids: ["n"], seconds: 8, aspect_ratio: "16:9", approved: false, decision: null, issues: [], assets: [], ai_review: null, shots: [{ ...shot, scene_id: "SCN-1", design: {}, source: shot.evidence }] };
beforeEach(() => {
  vi.restoreAllMocks(); localStorage.clear();
  vi.spyOn(API, "deliveryPlans").mockResolvedValue([]);
  vi.spyOn(API, "listProjectTasks").mockResolvedValue({ items: [], total: 0, page: 1, page_size: 50 });
  vi.spyOn(API, "deliveryPreview").mockResolvedValue(structuredClone(initial));
  vi.spyOn(API, "getSceneBatchSource").mockResolvedValue({ text: "甲说：出发。", source_file: "source/book.txt", start: 0, end: 8, note_title: "第一章", part: 0, shots: [] });
});
function panel(assemble = vi.fn()) { return render(<DeliveryPanel projectName="demo" sourceBasis="src" selection={["SH-1"]} title="出发" disabled={false} revision={0} labels={new Map([["SH-1", "SH-001"]])} load={vi.fn()} locate={vi.fn()} openAsset={vi.fn()} assemble={assemble} />); }
it("requires an explicit human story decision before assembly; no automatic AI or media calls", async () => {
  const confirm = vi.spyOn(API, "confirmDelivery").mockImplementation(async () => { vi.mocked(API.deliveryPreview).mockResolvedValue({ ...initial, approved: true, decision: { basis: "basis", reviewer: "导演", story_intent: "让观众看懂人物携剑出发的行动", withheld: "保留身份悬念", story_checked: true, timing_checked: true, continuity_checked: true, decisions: {} } }); });
  const ai = vi.spyOn(API, "productionAdvice"); const assemble = vi.fn(); panel(assemble);
  fireEvent.click(screen.getByRole("button", { name: "组集参考与制作资料" }));
  expect(await screen.findByRole("heading", { name: "1 · 核对实际画面与台词" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "组为正式剧集" })).not.toBeInTheDocument();
  const save = screen.getByRole("button", { name: "保存当前版本的编导确认" }); expect(save).toBeDisabled();
  fireEvent.change(screen.getByRole("textbox", { name: /本集要讲清楚/ }), { target: { value: "让观众看懂人物携剑出发的行动" } });
  fireEvent.change(screen.getByRole("textbox", { name: /有意保留的悬念/ }), { target: { value: "保留身份悬念" } });
  for (const box of screen.getAllByRole("checkbox")) fireEvent.click(box);
  fireEvent.click(save);
  await waitFor(() => expect(confirm).toHaveBeenCalledOnce());
  expect(await screen.findByText(/当前版本已由编导确认/)).toBeInTheDocument();
  expect(ai).not.toHaveBeenCalled(); expect(assemble).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "下载已核对资料包" })).toBeDisabled();
});
it("hard structural problems cannot be waived by a human checkbox", async () => {
  vi.mocked(API.deliveryPreview).mockResolvedValue({ ...initial, issues: [{ id: "missing", code: "speaker_missing", hard: true, shot_id: "SH-1", segment: 0, details: { text: "出发" } }] });
  panel(); fireEvent.click(screen.getByRole("button", { name: "组集参考与制作资料" }));
  expect(await screen.findByText(/项待补信息/)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "保存当前版本的编导确认" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "前往 SH-001 修改" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "创建分集并保存编排" })).toBeEnabled();
  expect(screen.getByText(/创建分集时将登记为带编号的待定说话资产/)).toBeInTheDocument();
});
it("edits speech placement without adding an off-screen speaker to the visible cast", async () => {
  const save = vi.fn<(value: ShotEdit) => Promise<void>>().mockResolvedValue();
  render(<ExecutionEditor projectName="demo" batch="batch" shot={shot} label="SH-001" assets={[{ kind: "character", name: "甲", asset_code: "CHR-001" }]} proposal={false} disabled={false} close={vi.fn()} save={save} />);
  fireEvent.change(screen.getByRole("combobox", { name: "发声方式" }), { target: { value: "off_screen" } });
  fireEvent.click(screen.getByRole("button", { name: "保存" }));
  await waitFor(() => expect(save).toHaveBeenCalledOnce());
  expect(save.mock.calls[0]![0].segments[0]!.utterances[0]!.delivery).toBe("off_screen");
  expect(save.mock.calls[0]![0].segments[0]!.characters_in_scene).toEqual([]);
});
