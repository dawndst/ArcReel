import { useEffect, useEffectEvent, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { useTasksStore } from "@/stores/tasks-store";
import { errMsg } from "@/utils/async";
import type { TaskItem } from "@/types/task";
import type { DeliveryPlan } from "@/types/novel-workflow";

export function StoryReviewAction({ projectName, plan, sourceBasis, disabled, update }: {
  projectName: string; plan: DeliveryPlan; sourceBasis: string; disabled: boolean; update: (plan: DeliveryPlan) => void;
}) {
  const { t } = useTranslation("dashboard");
  const [task, setTask] = useState<TaskItem | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const shotKey = JSON.stringify(plan.shot_ids);
  const taskId = task?.task_id;
  const receive = useEffectEvent(update);
  useEffect(() => {
    let active = true;
    void API.listProjectTasks(projectName, { taskType: "text_novel_workflow", pageSize: 50 }).then(({ items }) => {
      const matching = items.find((item) => item.payload.action === "selection_story" && item.payload.source_basis === sourceBasis && item.payload.title === plan.title && JSON.stringify(item.payload.shot_ids) === shotKey);
      if (active && matching) setTask((current) => current ?? matching);
    }).catch((reason: unknown) => { if (active) setError(errMsg(reason)); });
    return () => { active = false; };
  }, [projectName, sourceBasis, plan.title, shotKey]);
  useEffect(() => {
    if (!taskId) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const current = await API.getTask(taskId!);
        if (!active) return;
        setTask(current); setError("");
        if (current.status === "succeeded") {
          const value = await API.deliveryPreview(projectName, JSON.parse(shotKey) as string[], plan.title, sourceBasis, true);
          if (active) receive(value);
        } else if (current.status === "queued" || current.status === "running") timer = setTimeout(() => void poll(), 2000);
      } catch (reason) { if (active) setError(errMsg(reason)); }
    }
    void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [taskId, projectName, sourceBasis, plan.title, shotKey]);
  const pending = starting || task?.status === "queued" || task?.status === "running";
  async function start() {
    if (disabled || pending) return;
    setStarting(true); setError("");
    try {
      const response = await API.productionAdvice(projectName, "selection_story", plan.note_ids, plan.shot_ids, sourceBasis, plan.title);
      const member = response.batch.members[0];
      if (!member?.task_id) throw new Error(t("nw_story_not_submitted"));
      setTask(await API.getTask(member.task_id));
      await useTasksStore.getState().refreshTasks();
    } catch (reason) { setError(errMsg(reason)); } finally { setStarting(false); }
  }
  async function refresh() {
    try {
      setError("");
      if (taskId) setTask(await API.getTask(taskId));
      update(await API.deliveryPreview(projectName, plan.shot_ids, plan.title, sourceBasis, true));
    } catch (reason) { setError(errMsg(reason)); }
  }
  const recovered = plan.ai_review?.recovered_from_task === task?.task_id;
  const failed = !recovered && (task?.status === "failed" || task?.status === "cancelled");
  return <div className="space-y-3 rounded border bg-muted/10 p-3">
    <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={disabled || pending} onClick={() => void start()}>{pending && <Loader2 className="size-4 animate-spin" />}{t(pending ? "nw_story_checking" : failed ? "nw_story_retry" : "nw_delivery_ai")}</Button><Button size="sm" variant="ghost" disabled={starting} onClick={() => void refresh()}>{t("nw_delivery_refresh")}</Button></div>
    {pending && <p role="status" className="text-sm text-primary">{t(task?.status === "queued" ? "nw_story_queued" : "nw_story_running")}</p>}
    {failed && <div role="alert" className="space-y-2 rounded border border-destructive/30 bg-destructive/5 p-3 text-sm"><p className="font-semibold">{t("nw_story_failed")}</p>{task?.error_message && <details><summary className="cursor-pointer">{t("nw_story_error_detail")}</summary><p className="mt-2 whitespace-pre-wrap">{task.error_message}</p></details>}</div>}
    {!pending && plan.ai_review && <p role="status" className="text-sm font-semibold text-primary">{t("nw_story_complete", { count: plan.ai_review.findings.length })}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>;
}
