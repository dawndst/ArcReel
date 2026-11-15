import { useTranslation } from "react-i18next";
import type { ChapterNote, NovelWorkflow } from "@/types/novel-workflow";

type SceneStatus = NonNullable<NovelWorkflow["scene_status"]>[string];

export function SceneProgress({ note, status }: { note: ChapterNote; status: SceneStatus }) {
  const { t } = useTranslation("dashboard");
  const label = status.status === "complete" ? "nw_scene_ready_to_select" : status.status === "stale" ? "nw_scene_needs_update" : "nw_scene_incomplete";
  return <details className="basis-full rounded-lg border bg-card p-3 text-sm">
    <summary className="cursor-pointer font-semibold">
      {note.title} · {t(label)} · {status.completed}/{status.total ?? t("nw_scene_unplanned")}
    </summary>
    <progress aria-label={t("nw_scene_progress", { title: note.title })} className="mt-2 w-full accent-primary" value={status.total ? status.completed : undefined} max={status.total || undefined} />
    <ol className="mt-3 space-y-2">
      {status.units.map((unit) => <li key={unit.id} className="rounded border bg-muted/15 p-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <strong>{unit.id} · {unit.title}</strong>
          <span className={unit.status === "failed" ? "font-semibold text-destructive" : "text-muted-foreground"}>
            {t(unit.status === "running" && unit.stage === "reviewing" ? "nw_scene_unit_reviewing" : `nw_scene_unit_${unit.status}`)}
          </span>
        </div>
        {unit.error && <details className="mt-2 text-destructive"><summary className="cursor-pointer text-xs">{t("nw_scene_local_error")}</summary><p className="mt-2 whitespace-pre-wrap break-words text-xs">{unit.error}</p></details>}
      </li>)}
    </ol>
    <p className="mt-3 text-xs leading-6 text-muted-foreground">{t("nw_scene_repair_limits", { limit: status.repair_limit ?? 3 })}</p>
  </details>;
}
