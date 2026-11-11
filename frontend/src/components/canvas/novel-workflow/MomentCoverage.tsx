import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { SceneLibraryBatch, ShotMoment } from "@/types/novel-workflow";

export function MomentCoverage({ batches, selected, locate }: { batches: SceneLibraryBatch[]; selected: string[]; locate: (id: string) => void }) {
  const { t } = useTranslation("dashboard");
  const moments = new Map<string, ShotMoment>();
  for (const b of batches.filter((b) => !b.stale && !b.production_stale)) for (const m of b.production_context?.moments ?? []) {
    const previous = moments.get(m.id);
    moments.set(m.id, previous ? { ...previous, dialogues: [...new Map([...previous.dialogues, ...m.dialogues].map((d) => [d.id, d])).values()] } : m);
  }
  if (!moments.size) return null;
  const shots = batches.filter((b) => !b.stale && !b.production_stale).flatMap((b) => b.scenes.flatMap((s) => s.shots)).filter((s) => !selected.length || selected.includes(s.id));
  return <details className="rounded-lg border p-3 text-sm"><summary className="cursor-pointer font-semibold">{t(selected.length ? "nw_selected_coverage" : "nw_library_coverage")}</summary><p className="mt-2 text-muted-foreground">{t("nw_coverage_hint")}</p><div className="mt-3 space-y-3">{[...moments.values()].map((m) => {
    const linked = shots.filter((sh) => sh.production?.moment_ids.includes(m.id));
    const dialogueIds = new Set(linked.flatMap((sh) => sh.production?.dialogue_sources.map((d) => d.dialogue_id) ?? []));
    const covered = m.dialogues.filter((d) => dialogueIds.has(d.id)).length;
    return <div key={m.id} className="space-y-1 border-b pb-2 last:border-0"><p>{m.scene}</p><p className={linked.length && covered === m.dialogues.length ? "text-primary" : "text-warn"}>{t("nw_coverage_count", { shots: linked.length, covered, total: m.dialogues.length })}</p><Button size="sm" variant="link" onClick={() => locate(m.id)}>{t("nw_locate_moment")}</Button></div>;
  })}</div></details>;
}
