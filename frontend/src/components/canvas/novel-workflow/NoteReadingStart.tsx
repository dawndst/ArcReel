import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChapterNote } from "@/types/novel-workflow";

export function NoteReadingRange({ notes, selected, disabled, select, children }: { notes: ChapterNote[]; selected: string[]; disabled: boolean; select: (ids: string[]) => void; children?: (ids: string[], valid: boolean) => ReactNode }) {
  const { t } = useTranslation("dashboard");
  const initial = notes.filter((note) => selected.includes(note.id));
  const [from, setFrom] = useState(String(initial[0]?.order ?? 1));
  const [to, setTo] = useState(String(initial.at(-1)?.order ?? 1));
  const start = Number(from), end = Number(to);
  const valid = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && end >= start && end <= notes.length;
  const range = valid ? notes.slice(start - 1, end).map((note) => note.id) : [];
  return <section className="space-y-3 rounded-lg border p-4">
    <h3 className="text-sm font-semibold">{t("nw_read_range")}</h3>
    <p className="text-xs leading-relaxed text-muted-foreground">{t("nw_settings_range_hint")}</p>
    <div className="flex flex-wrap items-end gap-3">
      <label className="space-y-1 text-sm"><span className="block">{t("nw_from_chapter")}</span><Input type="number" min={1} max={notes.length} value={from} onChange={(e) => setFrom(e.target.value)} className="w-24" disabled={disabled} /></label>
      <label className="space-y-1 text-sm"><span className="block">{t("nw_to_chapter")}</span><Input type="number" min={1} max={notes.length} value={to} onChange={(e) => setTo(e.target.value)} className="w-24" disabled={disabled} /></label>
      <Button size="sm" variant="outline" disabled={disabled || !valid} onClick={() => select(range)}>{t("nw_range_use_for_task")}</Button>
      <span className="text-xs text-muted-foreground">{t("nw_settings_range_count", { count: range.length })}</span>
    </div>
    {children?.(range, valid)}
  </section>;
}
