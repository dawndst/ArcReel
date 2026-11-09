import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChapterNote, NovelWorkflow } from "@/types/novel-workflow";

export function ReadingScopePanel({ notes, scope, selected, disabled, select, save }: {
  notes: ChapterNote[]; scope: NovelWorkflow["scope"]; selected: string[]; disabled: boolean;
  select: (ids: string[]) => void; save: () => void;
}) {
  const { t } = useTranslation("dashboard");
  const [start, setStart] = useState(1);
  const [end, setEnd] = useState(Math.min(3, notes.length));
  const valid = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && end >= start && end <= notes.length;
  return <section aria-label={t("nw_scope_title")} className="shrink-0 space-y-2 border-b bg-primary/5 px-5 py-3">
    <div className="flex flex-wrap items-center gap-2"><h2 className="text-sm font-semibold">{t("nw_scope_title")}</h2>
      <span className="text-xs text-muted-foreground">{scope?.configured ? t("nw_scope_progress", { available: scope.available_count, read: scope.read_count, total: scope.total_count }) : t("nw_scope_unset")}</span>
    </div>
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-xs text-muted-foreground">{t("nw_scope_start")}<Input className="mt-1 w-24" type="number" min={1} max={notes.length} value={start} disabled={disabled} onChange={(e) => setStart(Number(e.target.value))} /></label>
      <label className="text-xs text-muted-foreground">{t("nw_scope_end")}<Input className="mt-1 w-24" type="number" min={start} max={notes.length} value={end} disabled={disabled} onChange={(e) => setEnd(Number(e.target.value))} /></label>
      <Button variant="outline" size="sm" disabled={disabled || !valid} onClick={() => select(notes.slice(start - 1, end).map((n) => n.id))}>{t("nw_scope_select")}</Button>
      <Button variant="outline" size="sm" disabled={disabled || !selected.length} onClick={save}>{t("nw_scope_set")}</Button>
    </div>
    <p className="text-xs leading-relaxed text-muted-foreground">{t("nw_scope_hint")}</p>
  </section>;
}
