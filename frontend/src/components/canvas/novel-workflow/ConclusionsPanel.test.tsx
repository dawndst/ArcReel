import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { ChapterNote } from "@/types/novel-workflow";
import { ConclusionsPanel } from "./ConclusionsPanel";

const notes = [{ id:"n", order:1, title:"第一章", reading:{conclusion_review:{basis:"review", conclusions:[{id:"q", question:"来人的身份？", answer:"尚未揭晓", status:"unrevealed", production_constraint:"保留背影", evidence_ids:[], evidence:[], blocking:false}]}}}] as unknown as ChapterNote[];

it("filters conclusions and requires evidence before a human can mark one resolved", () => {
  const decide = vi.fn();
  render(<ConclusionsPanel notes={notes} busy={false} decide={decide} />);
  fireEvent.click(screen.getByRole("button", { name: "已解释 (0)" }));
  expect(screen.queryByText("来人的身份？")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "剧情尚未揭晓 (1)" }));
  fireEvent.click(screen.getByRole("button", { name: "人工处理" }));
  fireEvent.change(screen.getAllByRole("combobox")[1]!, { target:{value:"resolved"} });
  fireEvent.change(screen.getByRole("textbox", {name:"判断依据说明"}), {target:{value:"已阅读原文"}});
  expect(screen.getByRole("button", {name:"保存决定并更新导览（调用AI）"})).toBeDisabled();
  fireEvent.change(screen.getAllByRole("combobox")[1]!, {target:{value:"unrevealed"}});
  fireEvent.click(screen.getByRole("button", {name:"保存决定并更新导览（调用AI）"}));
  expect(decide).toHaveBeenCalledWith({note_id:"n", conclusion_id:"q", status:"unrevealed", answer:"尚未揭晓", reason:"已阅读原文", evidence_ids:[]});
});

it("lets a human search and select source evidence omitted by the model", () => {
  const decide = vi.fn();
  const withEvidence = structuredClone(notes);
  withEvidence[0]!.reading!.conclusion_review!.available_evidence = [
    { id:"source-new", note_id:"n", source_file:"novel.txt", start:10, end:20, quote:"来人自称林舟" },
    { id:"other", note_id:"n", source_file:"novel.txt", start:30, end:40, quote:"窗外下起雨" },
  ];
  render(<ConclusionsPanel notes={withEvidence} busy={false} decide={decide} />);
  fireEvent.click(screen.getByRole("button", { name:"人工处理" }));
  fireEvent.change(screen.getAllByRole("combobox")[1]!, { target:{value:"resolved"} });
  fireEvent.change(screen.getByRole("textbox", {name:"判断依据说明"}), {target:{value:"原文直接说明身份"}});
  const save = screen.getByRole("button", {name:"保存决定并更新导览（调用AI）"});
  expect(save).toBeDisabled();
  fireEvent.click(screen.getByText("选择原文依据（已选 0 条）"));
  fireEvent.change(screen.getByRole("textbox", {name:"搜索原文依据"}), {target:{value:"林舟"}});
  expect(screen.queryByText("窗外下起雨")).not.toBeInTheDocument();
  const evidence = screen.getByRole("checkbox", {name:/来人自称林舟/});
  fireEvent.click(evidence);
  expect(save).toBeEnabled();
  fireEvent.click(save);
  expect(decide).toHaveBeenCalledWith(expect.objectContaining({status:"resolved", evidence_ids:["source-new"]}));
  fireEvent.click(evidence);
  expect(save).toBeDisabled();
});
