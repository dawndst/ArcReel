import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChapterNote } from "@/types/novel-workflow";

export function NoteReadingStart({ notes, selected, disabled, select, read }: { notes: ChapterNote[]; selected: string[]; disabled: boolean; select: (ids: string[]) => void; read: () => void }) {
  const { t } = useTranslation("dashboard");
  const [from, setFrom] = useState("1");
  const [to, setTo] = useState("1");
  const start = Number(from), end = Number(to);
  const valid = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && end >= start && end <= notes.length;
  const completed = notes.filter((note) => note.status === "read").length;
  return <section aria-label={t("nw_read_start")} className="shrink-0 space-y-3 border-b bg-primary/5 px-5 py-4">
    <div><h2 className="font-semibold">{t("nw_read_start")}</h2><p className="mt-1 text-sm text-muted-foreground">{t("nw_read_start_hint")}</p></div>
    <div className="flex flex-wrap items-end gap-3">
      <label className="space-y-1 text-sm"><span className="block">{t("nw_from_chapter")}</span><Input type="number" min={1} max={notes.length} value={from} onChange={(e) => setFrom(e.target.value)} className="w-24" disabled={disabled} /></label>
      <label className="space-y-1 text-sm"><span className="block">{t("nw_to_chapter")}</span><Input type="number" min={1} max={notes.length} value={to} onChange={(e) => setTo(e.target.value)} className="w-24" disabled={disabled} /></label>
      <Button variant="outline" disabled={disabled || !valid} onClick={() => select(notes.slice(start - 1, end).map((note) => note.id))}>{t("nw_select_range")}</Button>
      <Button disabled={disabled || selected.length === 0} onClick={read}>{t("nw_read")} · {t("nw_selected", { count: selected.length })}</Button>
    </div>
    <p className="text-xs text-muted-foreground">{t("nw_read_counts", { total: notes.length, completed })}</p>
  </section>;
}
