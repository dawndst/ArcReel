import { expect, it } from "vitest";
import { workflowProgress } from "./workflow-progress";
it("does not label stale terminal progress as reading", () => {
  for (const phase of ["failed", "complete", "stopped", "unknown"]) {
    expect(workflowProgress({ phase, done: 1, total: 3 })).toEqual({ label: "nw_task_preparing", showCounts: false });
  }
});
it("distinguishes review stages from novel reading", () => {
  expect(workflowProgress({ phase: "review", step: "analysis", done: 1, total: 3 }).label).toBe("nw_review_running");
  expect(workflowProgress({ phase: "review", step: "overview", done: 0, total: 1 }).label).toBe("nw_review_stage_overview");
  expect(workflowProgress({ phase: "review", step: "conclusion", done: 0, total: 1 }).label).toBe("nw_review_stage_conclusion");
});
