import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { API } from "@/api";
import type { TaskItem } from "@/types/task";
import type { DeliveryPlan } from "@/types/novel-workflow";
import { StoryReviewAction } from "./StoryReviewAction";

const plan: DeliveryPlan = { basis: "basis", title: "演示", shot_ids: ["SH-1"], note_ids: ["n"], seconds: 8, aspect_ratio: "16:9", approved: false, decision: null, issues: [], assets: [], ai_review: null, shots: [] };
function task(status: TaskItem["status"]): TaskItem { return { task_id: "review-task", project_name: "demo", task_type: "text_novel_workflow", media_type: "render", resource_id: "novel-workflow", resource_type: null, script_file: null, payload: { action: "selection_story", source_basis: "src", title: "演示", shot_ids: ["SH-1"] }, status, result: null, error_message: status === "failed" ? "引用格式未通过检查" : null, cancelled_by: null, provider_id: null, provider_job_id: null, source: "webui", queued_at: "2026-11-12T10:00:00Z", started_at: null, finished_at: null, updated_at: "2026-11-12T10:00:00Z" }; }
beforeEach(() => vi.restoreAllMocks());
it("restores running reviews and automatically loads their completed result", async () => {
  vi.spyOn(API, "listProjectTasks").mockResolvedValue({ items: [task("running")], total: 1, page: 1, page_size: 50 });
  vi.spyOn(API, "getTask").mockResolvedValueOnce(task("running")).mockResolvedValue(task("succeeded"));
  const complete = { ...plan, ai_review: { summary: "故事因果可理解", audience_understanding: "人物决定出发", findings: [] } };
  vi.spyOn(API, "deliveryPreview").mockResolvedValue(complete);
  const update = vi.fn();
  render(<StoryReviewAction projectName="demo" plan={plan} sourceBasis="src" disabled={false} update={update} />);
  expect(await screen.findByText(/完成后自动显示结果/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "正在检查观众理解" })).toBeDisabled();
  await waitFor(() => expect(update).toHaveBeenCalledWith(complete), { timeout: 4000 });
});
it("shows a failed previous review next to the retry button after reopening", async () => {
  vi.spyOn(API, "listProjectTasks").mockResolvedValue({ items: [task("failed")], total: 1, page: 1, page_size: 50 });
  vi.spyOn(API, "getTask").mockResolvedValue(task("failed"));
  render(<StoryReviewAction projectName="demo" plan={plan} sourceBasis="src" disabled={false} update={vi.fn()} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("这次检查未完成");
  expect(screen.getByRole("button", { name: "重新检查观众理解" })).toBeEnabled();
  expect(screen.getByText("查看失败详情")).toBeInTheDocument();
});
