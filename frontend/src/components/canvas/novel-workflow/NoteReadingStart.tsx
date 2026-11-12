import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChapterNote } from "@/types/novel-workflow";

export function NoteReadingStart({ notes, selected, disabled, select, read, children }: { notes: ChapterNote[]; selected: string[]; disabled: boolean; select: (ids: string[]) => void; read: () => void; children?: ReactNode }) {
  const { t } = useTranslation("dashboard");
  const [from, setFrom] = useState("1");
  const [to, setTo] = useState("1");
  const start = Number(from), end = Number(to);
  const valid = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && end >= start && end <= notes.length;
  const completed = notes.filter((note) => note.status === "read").length;
  return <section aria-label={t("nw_read_start")} className="shrink-0 border-b bg-primary/5">
    <div className="flex flex-wrap items-center justify-between gap-2 px-5 py-2">
      <span className="text-sm font-medium">{t("nw_read_progress", { total: notes.length, completed })}</span>
      <Button size="sm" disabled={disabled || selected.length === 0} onClick={read}>{t("nw_read")} · {t("nw_selected", { count: selected.length })}</Button>
    </div>
    <details open={completed === 0 ? true : undefined} className="group px-5 pb-2">
      <summary className="cursor-pointer text-sm text-muted-foreground">{t("nw_read_range")}</summary>
      <div className="relative max-h-60 space-y-3 overflow-y-auto pt-3 [scrollbar-gutter:stable]">
        <p className="text-xs leading-relaxed text-muted-foreground">{t("nw_read_start_hint")}</p>
        <div className="flex flex-wrap items-end gap-3">
          <label className="space-y-1 text-sm"><span className="block">{t("nw_from_chapter")}</span><Input type="number" min={1} max={notes.length} value={from} onChange={(e) => setFrom(e.target.value)} className="w-24" disabled={disabled} /></label>
          <label className="space-y-1 text-sm"><span className="block">{t("nw_to_chapter")}</span><Input type="number" min={1} max={notes.length} value={to} onChange={(e) => setTo(e.target.value)} className="w-24" disabled={disabled} /></label>
          <Button size="sm" variant="outline" disabled={disabled || !valid} onClick={() => select(notes.slice(start - 1, end).map((note) => note.id))}>{t("nw_select_range")}</Button>
        </div>
        {children}
      </div>
    </details>
  </section>;
}
