import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { ChapterNote, UnderstandingReport, UnderstandingLink } from "@/types/novel-workflow";
import { QuestionRegisterPanel } from "./QuestionRegisterPanel";

const notes: ChapterNote[] = [
  { id: "n1", title: "第一章", order: 1, volume: "", chapter: "", chars: 100, basis: "b", sections: [] },
  { id: "n2", title: "第二章", order: 2, volume: "", chapter: "", chars: 100, basis: "c", sections: [] },
];
const link: UnderstandingLink = {
  id: "l1", kind: "state", subject: "主人称呼", description: "景麒称阳子为主人，制度依据未知。",
  status: "uncertain", claim_type: "statement", source_kind: "narrative", perspective: "景麒", story_time: "现在",
  story_start_note_id: null, story_end_note_id: null, note_ids: ["n1"], evidence: [], revealed_at: { note_id: "n1", order: 1, offset: 10 },
};
const report: UnderstandingReport = {
  id: "r1", stale: false, created_at: "2026-11-13T00:00:00Z", selected_note_ids: ["n1", "n2"], searched_note_count: 2,
  inspected_note_ids: ["n1", "n2"], unread_inspected_note_ids: [], inspections: [],
  unresolved: [{ note_id: "n1", question: "为什么称主人" }, { note_id: "n2", question: "主从依据为何" }, { note_id: "n1", question: "说话人是否正确" }],
  question_register: {
    stale: false, original_count: 3, group_count: 2, counts: { plot_unrevealed: 1, extraction_check: 1 },
    originals: [{ id: "q1", index: 0, note_id: "n1", question: "为什么称主人" }, { id: "q2", index: 1, note_id: "n2", question: "主从依据为何" }, { id: "q3", index: 2, note_id: "n1", question: "说话人是否正确" }],
    groups: [
      { id: "g1", question: "主人称呼的制度依据", kind: "plot_unrevealed", explanation: "留待后续剧情解释", original_ids: ["q1", "q2"], note_ids: ["n1", "n2"], link_ids: ["l1"], original_count: 2 },
      { id: "g2", question: "对白说话人是否正确", kind: "extraction_check", explanation: "核对发言上下文", original_ids: ["q3"], note_ids: ["n1"], link_ids: [], original_count: 1 },
    ],
  },
};

it("separates actionable checks from story mysteries and retains source navigation and originals", async () => {
  const user = userEvent.setup(); const select = vi.fn();
  render(<QuestionRegisterPanel report={report} notes={notes} links={[link]} select={select} busy={false} />);
  expect(screen.getByRole("heading", { name: "对白说话人是否正确" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "主人称呼的制度依据" })).not.toBeInTheDocument();
  expect(screen.getByText("3 条原始提示 → 2 个归并问题")).toBeVisible();
  await user.click(screen.getByRole("tab", { name: /剧情悬念/ }));
  expect(screen.getByRole("heading", { name: "主人称呼的制度依据" })).toBeVisible();
  expect(screen.getByText("归并自 2 条原始提示")).toBeVisible();
  expect(screen.getByText("为什么称主人")).toBeInTheDocument();
  expect(screen.getByText("主从依据为何")).toBeInTheDocument();
  expect(screen.getByText(link.description)).toBeInTheDocument();
  expect(screen.getByText(/这些材料仅供理解与核对/)).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "查看来源章节" }));
  expect(select).toHaveBeenCalledWith(["n1", "n2"]);
});

it("keeps unsummarized originals collapsed and starts only the explicit organize action", () => {
  const organize = vi.fn();
  render(<QuestionRegisterPanel report={{ ...report, question_register: null }} notes={notes} links={[]} select={vi.fn()} organize={organize} busy={false} />);
  const summary = screen.getByText("查看原始提示（3）");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  fireEvent.click(screen.getByRole("button", { name: "AI 整理待查问题" }));
  expect(organize).toHaveBeenCalledTimes(1);
});

it("disables organizing while another workflow is active or the report is stale", () => {
  const { rerender } = render(<QuestionRegisterPanel report={report} notes={notes} links={[]} select={vi.fn()} organize={vi.fn()} busy />);
  expect(screen.getByRole("button", { name: "更新问题台账" })).toBeDisabled();
  rerender(<QuestionRegisterPanel report={{ ...report, stale: true }} notes={notes} links={[]} select={vi.fn()} organize={vi.fn()} busy={false} />);
  expect(screen.getByRole("button", { name: "更新问题台账" })).toBeDisabled();
});

it("includes the chapters of linked evidence when opening the source material", async () => {
  const user = userEvent.setup(); const select = vi.fn();
  const value = { ...report, question_register: { ...report.question_register!, groups: report.question_register!.groups.map((g) => ({ ...g, note_ids: ["n1"] })) } };
  render(<QuestionRegisterPanel report={value} notes={notes} links={[{ ...link, note_ids: ["n2"] }]} select={select} busy={false} />);
  await user.click(screen.getByRole("tab", { name: /剧情悬念/ }));
  await user.click(screen.getByRole("button", { name: "查看来源章节" }));
  expect(select).toHaveBeenCalledWith(["n1", "n2"]);
});
