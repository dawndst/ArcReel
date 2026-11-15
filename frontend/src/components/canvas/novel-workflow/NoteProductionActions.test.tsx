import { SceneProgress } from "./SceneProgress";
import { render, screen, fireEvent } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { NovelWorkflow } from "@/types/novel-workflow";
import { NoteProductionActions, noteProductionStatus } from "./NoteProductionActions";

const data: NovelWorkflow = {
  initialized: true, stale: false, source_basis: "source", groups: [], progress: null,
  notes: [{ id: "n", title: "第一章", order: 1, volume: "", chapter: "", chars: 100, basis: "b", sections: [], status: "read", svt_id: "svt", svt_status: "complete" }],
  svts: [{ id: "svt", title: "主线", summary: "", note_ids: ["n"], status: "open", mainline_reason: "", breakdown_status: "complete", climaxes: [], payoffs: [], dialogues: [], evidence: [] }],
  scene_status: { n: { status: "complete", completed: 1, total: 1, retained_drafts: 0, units: [] } },
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

it("delegates re-extraction to the centrally confirmed API", async () => {
  const run = vi.fn().mockResolvedValue(undefined);
  render(<NoteProductionActions data={data} notes={data.notes} canSvt canScenes busy={false} run={run} viewSvt={() => {}} viewScenes={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "更新已有成果" }));
  fireEvent.click(await screen.findByRole("menuitem", { name: "重新提炼／补全 SVT" }));
  expect(run).toHaveBeenCalledWith("svt", ["n"]);
});

it("does not label mixed or outdated selections complete", () => {
  const mixed = [...data.notes, { ...data.notes[0]!, id: "n2", svt_id: null, svt_status: "unassigned" }];
  expect(noteProductionStatus(data, mixed)).toMatchObject({ svtComplete: false, scenesForAll: false });
  expect(noteProductionStatus({ ...data, svt_stale: true }, data.notes).svtComplete).toBe(true);
  expect(noteProductionStatus({ ...data, svts: data.svts.map((s) => ({ ...s, stale: true })) }, data.notes).svtComplete).toBe(false);
  expect(noteProductionStatus({ ...data, stale: true }, data.notes).svtComplete).toBe(false);
  expect(noteProductionStatus({ ...data, scene_batches: data.scene_batches!.map((b) => ({ ...b, production_stale: true })) }, data.notes).scenesStale).toBe(true);
});


it("keeps a current primary complete when an older cross-chapter SVT is stale", () => {
  const mixed = { ...data, svt_stale: true, svts: [{ ...data.svts[0]!, id: "old", note_ids: ["n", "n2"], stale: true }, ...data.svts] };
  const run = vi.fn();
  render(<NoteProductionActions data={mixed} notes={data.notes} canSvt canScenes busy={false} run={run} viewSvt={() => {}} viewScenes={() => {}} />);
  expect(screen.getByRole("button", { name: "查看 SVT（已完成）" })).toBeInTheDocument();
  expect(noteProductionStatus(mixed, data.notes).svts.map((s) => s.id)).toEqual(["svt"]);
  expect(run).not.toHaveBeenCalled();
});

it("offers missing chapter outputs even when another selected chapter already has outputs", () => {
  const run=vi.fn();
  const notes=[...data.notes,{...data.notes[0]!,id:'n2',svt_id:null,svt_status:'unassigned'}];
  render(<NoteProductionActions data={{...data,notes}} notes={notes} canSvt canScenes busy={false} run={run} viewSvt={vi.fn()} viewScenes={vi.fn()} />);
  fireEvent.click(screen.getByRole('button',{name:'为未覆盖的 1 章提炼 SVT'}));
  expect(run).toHaveBeenCalledWith('svt',['n2']);
  fireEvent.click(screen.getByRole('button',{name:'继续完成 1 章场镜'}));
  expect(run).toHaveBeenCalledWith('scenes',['n2']);
});

it("does not mistake a retained legacy draft or one of four units for a complete chapter", () => {
  expect(noteProductionStatus({ ...data, scene_status: undefined }, data.notes).scenesForAll).toBe(false);
  const partial = { ...data, scene_status: { n: { status: "partial" as const, completed: 1, total: 4, units: [], retained_drafts: 1 } } };
  expect(noteProductionStatus(partial, data.notes).scenesForAll).toBe(false);
  const run=vi.fn();
  render(<NoteProductionActions data={partial} notes={data.notes} canSvt canScenes busy={false} run={run} viewSvt={vi.fn()} viewScenes={vi.fn()} />);
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  render(<SceneProgress note={data.notes[0]!} status={partial.scene_status.n} />);
  expect(screen.getByRole("progressbar")).toHaveAttribute("max", "4");
  fireEvent.click(screen.getByRole("button", {name:"继续完成 1 章场镜"}));
  expect(run).toHaveBeenCalledWith("scenes", ["n"]);
});
