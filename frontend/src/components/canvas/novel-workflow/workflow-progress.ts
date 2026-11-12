import type { NovelWorkflow } from "@/types/novel-workflow";

export function workflowProgress(progress: NovelWorkflow["progress"]) {
  const labels: Record<string, string> = {
    speaker_attribution: "nw_speaker_ai_running", reading: "nw_reading_running", condensing: "nw_condensing", summarizing: "nw_summarizing",
    scenes: progress?.step === "production" ? "nw_complete_production" : "nw_phase_scenes",
    group_summary: "nw_group_summarize", understanding: "nw_understanding_running",
    review: progress?.step === "overview" ? "nw_review_stage_overview" : progress?.step === "conclusion" ? "nw_review_stage_conclusion" : "nw_review_running",
    svt: "nw_svt_running",
  };
  const label = progress ? labels[progress.phase] : undefined;
  return { label: label ?? "nw_task_preparing", showCounts: !!label };
}
