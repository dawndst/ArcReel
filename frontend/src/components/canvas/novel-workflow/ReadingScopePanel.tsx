import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { ChapterNote, NovelWorkflow } from "@/types/novel-workflow";

export function ReadingScopePanel({ scope, notes, selected, disabled, save }: {
  scope: NovelWorkflow["scope"]; notes: ChapterNote[]; selected: string[]; disabled: boolean; save: (extend: boolean) => void;
}) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [restricting, setRestricting] = useState(false);
  const excluded = notes.filter((n) => (scope?.configured ? scope.note_ids.includes(n.id) : true) && !selected.includes(n.id));
  return <section className="rounded-lg border p-4 text-sm">
    <h3 className="font-semibold">{t("nw_scope_title")} · {scope?.configured ? t("nw_scope_progress", { available: scope.available_count, read: scope.read_count, total: scope.total_count }) : t("nw_scope_unset")}</h3>
    <div className="space-y-3 py-3">
      <p className="text-xs leading-6 text-muted-foreground">{t("nw_scope_hint")}</p>
      <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" disabled={disabled || !selected.length} onClick={() => save(true)}>{t("nw_scope_add")}</Button><Button variant="ghost" size="sm" disabled={disabled || !selected.length} onClick={() => setRestricting(true)}>{t("nw_scope_replace")}</Button></div>
      {restricting && <div className="space-y-3 rounded border border-warn/40 bg-warn/5 p-3"><p className="font-semibold">{t("nw_scope_replace_preview", { selected: selected.length, excluded: excluded.length })}</p><p className="text-xs leading-6 text-muted-foreground">{t("nw_scope_preserve_notes")}</p><p className="text-xs text-muted-foreground">{excluded.slice(0, 8).map((n) => n.title).join(" / ")}{excluded.length > 8 ? "…" : ""}</p><div className="flex flex-wrap gap-2"><Button variant="destructive" size="sm" disabled={disabled || !selected.length} onClick={() => { save(false); setRestricting(false); }}>{t("nw_scope_replace_confirm")}</Button><Button variant="outline" size="sm" onClick={() => setRestricting(false)}>{t("common:cancel")}</Button></div></div>}
    </div>
  </section>;
}
