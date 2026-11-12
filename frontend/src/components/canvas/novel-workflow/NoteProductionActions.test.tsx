import { render, screen, fireEvent, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { NovelWorkflow } from "@/types/novel-workflow";
import { NoteProductionActions, noteProductionStatus } from "./NoteProductionActions";

const data: NovelWorkflow = {
  initialized: true, stale: false, source_basis: "source", groups: [], progress: null,
  notes: [{ id: "n", title: "第一章", order: 1, volume: "", chapter: "", chars: 100, basis: "b", sections: [], status: "read", svt_id: "svt", svt_status: "complete" }],
  svts: [{ id: "svt", title: "主线", summary: "", note_ids: ["n"], status: "open", mainline_reason: "", breakdown_status: "complete", climaxes: [], payoffs: [], dialogues: [], evidence: [] }],
  scene_batches: [{ basis: "batch", note_id: "n", stale: false, skipped_reason: "", scenes: [{ id: "scene", title: "场", location: "", time: "", purpose: "", shots: [] }] }],
};

it("views existing outputs without starting model work", () => {
  const run = vi.fn(); const svt = vi.fn(); const scenes = vi.fn();
  render(<NoteProductionActions data={data} notes={data.notes} canSvt canScenes busy={false} run={run} viewSvt={svt} viewScenes={scenes} />);
  fireEvent.click(screen.getByRole("button", { name: "查看 SVT（已完成）" }));
  fireEvent.click(screen.getByRole("button", { name: "查看场镜（1场／0镜）" }));
  expect(svt).toHaveBeenCalledWith("svt"); expect(scenes).toHaveBeenCalledWith("batch");
  expect(run).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "生成场与镜头" })).not.toBeInTheDocument();
});

it("requires explicit confirmation for re-extraction", async () => {
  const run = vi.fn().mockResolvedValue(undefined);
  render(<NoteProductionActions data={data} notes={data.notes} canSvt canScenes busy={false} run={run} viewSvt={() => {}} viewScenes={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "更新已有成果" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "重新提炼／补全 SVT" }));
  const dialog = screen.getByRole("dialog");
  expect(within(dialog).getByText("第一章")).toBeInTheDocument();
  expect(run).not.toHaveBeenCalled();
  fireEvent.click(within(dialog).getByRole("button", { name: "确认更新所选章节" }));
  expect(run).toHaveBeenCalledWith("svt", ["n"]);
});

it("does not label mixed or outdated selections complete", () => {
  const mixed = [...data.notes, { ...data.notes[0]!, id: "n2", svt_id: null, svt_status: "unassigned" }];
  expect(noteProductionStatus(data, mixed)).toMatchObject({ svtComplete: false, scenesForAll: false });
  expect(noteProductionStatus({ ...data, svt_stale: true }, data.notes).svtComplete).toBe(false);
  expect(noteProductionStatus({ ...data, scene_batches: data.scene_batches!.map((b) => ({ ...b, production_stale: true })) }, data.notes).scenesStale).toBe(true);
});
