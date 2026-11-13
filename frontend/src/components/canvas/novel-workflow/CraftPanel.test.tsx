import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { CraftPanel } from "./CraftPanel";
import type { SceneLibraryBatch } from "@/types/novel-workflow";

const batch: SceneLibraryBatch = { basis: "b", note_id: "n", stale: true, skipped_reason: "", scenes: [{ id: "s", title: "拿书", location: "室内", time: "日", purpose: "决定", shots: [{ id: "SH1", title: "拿书", evidence: { note_id: "n", source_file: "book", start: 0, end: 4, quote: "甲拿起书" }, segments: [] }] }], craft: { basis: "c", revision: "r", stale: false, reading_available: true, review: null, items: [{ id: "e:action", event_id: "e", title: "拿书", kind: "行动", text: "甲拿起书", claim_type: "fact", source_kind: "narrative", evidence: { note_id: "n", source_file: "book", start: 0, end: 4, quote: "甲拿起书" }, suggestion: null, decision: null }] } };

it("keeps historical source inspection and explicit editorial decisions available", async () => {
  const save = vi.fn().mockResolvedValue(undefined), source = vi.fn(), run = vi.fn();
  render(<CraftPanel batch={batch} labels={new Map([["SH1", "SH-001"]])} disabled={false} save={save} run={run} locate={vi.fn()} source={source} />);
  fireEvent.click(screen.getByText(/前提、行动与结果/));
  fireEvent.click(screen.getByRole("button", { name: "查看原文依据" }));
  expect(source).toHaveBeenCalledWith(undefined, batch.craft!.items[0].evidence);
  fireEvent.click(screen.getByRole("button", { name: /^处理$/ }));
  fireEvent.click(screen.getByLabelText("明确省略"));
  fireEvent.change(screen.getByLabelText("处理依据（至少5字）"), { target: { value: "重复动作由编导省略" } });
  fireEvent.click(screen.getByRole("button", { name: "保存编导决定" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith("b", "r", expect.objectContaining({ item_id: "e:action", decision: "omit", reason: "重复动作由编导省略" })));
  expect(run).not.toHaveBeenCalled();
});

it("retains the form and shows failure instead of claiming success", async () => {
  render(<CraftPanel batch={batch} labels={new Map()} disabled={false} save={vi.fn().mockRejectedValue(new Error("版本已变化"))} locate={vi.fn()} source={vi.fn()} />);
  fireEvent.click(screen.getByText("各场开场状态"));
  fireEvent.click(screen.getByRole("button", { name: "编辑并确认开场状态" }));
  fireEvent.change(screen.getByLabelText("开场在场人物"), { target: { value: "甲" } });
  fireEvent.change(screen.getByLabelText("处理依据（至少5字）"), { target: { value: "人工核对开场状态" } });
  fireEvent.click(screen.getByRole("button", { name: "保存编导决定" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("版本已变化");
  expect(screen.getByLabelText("开场在场人物")).toHaveValue("甲");
});
