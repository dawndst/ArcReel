import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { ChapterNote, NoteGroup } from "@/types/novel-workflow";

export function NoteGroupsPanel({ groups, notes, disabled, select, summarize, usage, dissolve }: {
  groups: NoteGroup[]; notes: ChapterNote[]; disabled: boolean;
  select: (ids: string[]) => void; summarize: (group: NoteGroup) => void;
  usage: (group: NoteGroup) => void; dissolve: (id: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  return <div className="relative min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
    <p className="text-sm text-muted-foreground">{t("nw_group_management_hint")}</p>
    {!groups.length && <p>{t("nw_groups_empty")}</p>}
    {groups.map((group) => <article key={group.id} className="space-y-3 rounded-xl border p-4">
      <div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">{group.title}</h2><span className="rounded bg-muted px-2 py-1 text-xs">{t(group.usage === "reference" ? "nw_group_reference" : "nw_group_candidate")}</span></div>
      <p className="text-xs text-muted-foreground">{group.note_ids.map((id) => notes.find((n) => n.id === id)?.title ?? id).join(" / ")}</p>
      {group.summary_stale && <p className="text-sm text-destructive">{t("nw_group_summary_stale")}</p>}
      {group.synopsis ? <><p className="whitespace-pre-wrap text-sm leading-7">{group.synopsis.summary}</p><p className="text-sm"><strong>{t("nw_hook")}：</strong>{group.synopsis.hook}</p></> : <p className="text-sm text-muted-foreground">{t("nw_group_summary_empty")}</p>}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" disabled={disabled || group.note_ids.some((id) => notes.find((n) => n.id === id)?.status !== "read")} onClick={() => summarize(group)}>{t("nw_group_summarize")}</Button>
        <Button size="sm" variant="outline" onClick={() => select(group.note_ids)}>{t("nw_group_view_notes")}</Button>
        <Button size="sm" variant="outline" disabled={disabled} onClick={() => usage(group)}>{t(group.usage === "reference" ? "nw_group_make_candidate" : "nw_group_make_reference")}</Button>
        <Button size="sm" variant="destructive" disabled={disabled} onClick={() => dissolve(group.id)}>{t("nw_dissolve")}</Button>
      </div>
    </article>)}
  </div>;
}
