import { useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { refreshAfterWrite } from "@/components/canvas/shared/refreshAfterWrite";
import { useTasksStore } from "@/stores/tasks-store";
import type { NovelAdoption, NovelReport, NovelStatus } from "@/types/novel-understanding";
import { episodePosition, type EpisodeLedger } from "@/utils/episode-display";
import { errMsg } from "@/utils/async";

export function NovelUnderstandingPanel({ projectName, planning, onChanged, episodes = [] }: {
  projectName: string; planning: boolean; onChanged: () => void; episodes?: EpisodeLedger;
}) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [status, setStatus] = useState<NovelStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ report: NovelReport; result: NovelAdoption } | null>(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await API.getNovelUnderstanding(projectName, { signal: controller.signal });
        if (controller.signal.aborted) return;
        setStatus(next);
      } catch (cause) {
        if (!controller.signal.aborted) setError(errMsg(cause));
      }
      if (!controller.signal.aborted) timer = setTimeout(() => { void poll(); }, 5000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [projectName, revision]);

  const review = useCallback(async () => {
    setBusy(true); setError(null);
    try {
      await API.reviewNovelUnderstanding(projectName);
      await useTasksStore.getState().refreshTasks();
      setRevision((n) => n + 1);
    } catch (cause) { setError(errMsg(cause)); }
    finally { setBusy(false); }
  }, [projectName]);

  async function adopt(report: NovelReport, confirmed?: NovelAdoption) {
    setBusy(true); setError(null);
    try {
      const impact = confirmed?.impact;
      const result = await API.adoptNovelDecision(projectName, {
        report_id: report.id, dry_run: !confirmed,
        confirm_episodes: impact ? [...impact.restaled, ...impact.retired] : [],
        confirm_merged_units: impact?.merged_units ?? 0,
      });
      if (result.status === "confirmation_required") setPending({ report, result });
      else {
        setPending(null);
        await refreshAfterWrite(projectName, t);
        setRevision((n) => n + 1); onChanged();
      }
    } catch (cause) { setError(errMsg(cause)); }
    finally { setBusy(false); }
  }

  if (status?.supported === false || (!status && !error)) return null;
  return (
    <div className="shrink-0 border-b bg-muted/20 px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <strong className="text-sm">{t("dashboard:novel_understanding_title")}</strong>
          <p className="text-xs text-muted-foreground" role="status">
            {planning && `${t("dashboard:novel_working")} · `}
            {status?.enabled ? t(`dashboard:novel_phase_${status.phase}`, { defaultValue: status.phase }) : t("dashboard:novel_off")}
            {status?.enabled && status.total_chunks > 0 && ` · ${status.coverage ?? 0}% (${status.completed_chunks}/${status.total_chunks})`}
          </p>
        </div>
        <Button size="sm" disabled={busy || planning || !status?.enabled} onClick={() => { void review(); }}>
          {t("dashboard:novel_review")}
        </Button>
      </div>
      {error && <p className="mt-2 text-sm text-destructive" role="alert">{error}</p>}
      {status?.error && <details className="mt-2 text-sm"><summary>{t("dashboard:novel_failure")}</summary>{status.error}</details>}
      {!!status?.reports.length && <details className="mt-2">
        <summary className="cursor-pointer text-sm font-medium">{t("dashboard:novel_suggestions", { count: status.reports.length })}</summary>
        <div className="relative mt-2 max-h-80 space-y-3 overflow-y-auto">
          {status.reports.map((report) => <article key={report.id} className="rounded-lg border bg-background p-3 text-sm">
            <strong>{episodePosition(episodes, report.episode) !== null && `${t("common:episode_position_name", { position: episodePosition(episodes, report.episode) })} · `}{report.decision.title}</strong>
            <span className="ml-2 rounded bg-primary/10 px-2 py-0.5 text-primary">{t(`dashboard:novel_action_${report.decision.action}`)}</span>
            <p className="my-2">{report.decision.reason}</p>
            {(["must_film", "compress", "omit", "preserve_setup"] as const).map((field) => report.decision[field].length > 0 && (
              <div key={field} className="mt-1"><strong>{t(`dashboard:novel_${field}`)}：</strong>{report.decision[field].join("；")}</div>
            ))}
            <details className="my-2"><summary className="cursor-pointer">{t("dashboard:novel_proposed_outline")}</summary>
              <ol className="list-inside list-decimal">{report.decision.story_beats.map((beat, index) => <li key={index}>{beat}</li>)}</ol>
              <p>{report.decision.hook}</p>
              {report.evidence.map((e, index) => <blockquote key={index} className="my-2 border-l-2 pl-3 text-muted-foreground">{e.quote}<footer className="text-xs">{e.source_file} · {e.start}–{e.end}</footer></blockquote>)}
            </details>
            <Button size="sm" disabled={busy || planning} onClick={() => { void adopt(report); }}>{t("dashboard:novel_adopt")}</Button>
          </article>)}
        </div>
      </details>}
      <Dialog open={pending !== null} onOpenChange={(open) => { if (!open && !busy) setPending(null); }}>
        <DialogContent>
          <DialogTitle>{t("dashboard:novel_adopt")}</DialogTitle>
          <DialogDescription>{pending?.result.impact?.text}</DialogDescription>
          <p className="text-sm">{pending?.report.decision.title}</p>
          <DialogFooter>
            <Button variant="outline" disabled={busy} onClick={() => setPending(null)}>{t("common:cancel")}</Button>
            <Button disabled={busy} onClick={() => { if (pending) void adopt(pending.report, pending.result); }}>{t("common:confirm")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
