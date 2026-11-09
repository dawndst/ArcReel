import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Loader2 } from "lucide-react";
import { API } from "@/api";
import type { NovelStatus } from "@/types/novel-understanding";

/** Display the actual reading prerequisite while the enclosing task is labelled script planning. */
export function NovelReadingProgress({ projectName, active, notebook = false }: { projectName: string; active: boolean; notebook?: boolean }) {
  const { t } = useTranslation("dashboard");
  const [status, setStatus] = useState<NovelStatus | null>(null);
  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const memory = notebook ? await API.getNovelWorkflow(projectName, { signal: controller.signal }) : null;
        const value = notebook ? {
          enabled: true, phase: ["svt", "review", "understanding"].includes(memory?.progress?.phase ?? "") ? "synthesizing" : memory?.progress?.phase ?? "idle",
          completed_chunks: memory?.progress?.done ?? 0, total_chunks: memory?.progress?.total ?? 0,
          coverage: memory?.progress?.total ? Math.round(memory.progress.done / memory.progress.total * 100) : 0, reports: [],
        } : await API.getNovelUnderstanding(projectName, { signal: controller.signal });
        if (!controller.signal.aborted) setStatus(value);
      } catch {
        if (!controller.signal.aborted) setStatus(null);
      }
      if (!controller.signal.aborted) timer = setTimeout(() => { void poll(); }, 5000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [projectName, active, notebook]);
  if (!active || !status?.enabled || !["reading", "synthesizing", "scenes", "group_summary"].includes(status.phase)) return null;
  return (
    <span role="status" title={t("novel_understanding_title")} className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs text-primary">
      <Loader2 aria-hidden className="size-3 animate-spin" />
      {t(status.phase === "scenes" ? "nw_phase_scenes" : status.phase === "group_summary" ? "nw_group_summarize" : `novel_phase_${status.phase}`)} · {status.coverage ?? 0}%
    </span>
  );
}
