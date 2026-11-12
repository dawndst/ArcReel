import { useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { errMsg } from "@/utils/async";
import type { ChapterEdition, ChapterNote } from "@/types/novel-workflow";

export function ChapterEditionPanel({ projectName, note, disabled, generate }: { projectName: string; note: ChapterNote; disabled: boolean; generate: () => void }) {
  const { t } = useTranslation("dashboard");
  const [value, setValue] = useState<ChapterEdition | null>(null);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  async function show() {
    if (value) { setOpen(!open); return; }
    setLoading(true); setError("");
    try { setValue(await API.getChapterEdition(projectName, note.id)); setOpen(true); }
    catch (e) { setError(errMsg(e)); }
    finally { setLoading(false); }
  }
  return <section className="space-y-3 rounded-xl border bg-card p-5 shadow-xs">
    <h3 className="text-base font-bold">{t("nw_edition_title")}</h3>
    <p className="text-xs leading-relaxed text-muted-foreground">{t("nw_edition_hint")}</p>
    {note.edition ? <><p className="text-sm">{t("nw_edition_counts", { original: note.edition.original_chars, edited: note.edition.edited_chars })}</p><Button size="sm" variant="outline" disabled={loading} onClick={() => void show()}>{t(open ? "nw_edition_hide" : "nw_edition_show")}</Button></> : <Button size="sm" variant="outline" disabled={disabled} onClick={generate}>{t("nw_edition_generate")}</Button>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {open && value && <div className="space-y-4">{value.parts.map((part, i) => <div key={i} className="space-y-3">{part.passages.map((p) => <div key={p.unit} className="space-y-2 text-sm">
      {p.text && <p className="leading-relaxed whitespace-pre-wrap">{p.text}</p>}
      <details className="rounded border p-2 text-xs text-muted-foreground"><summary className="cursor-pointer">{t(`nw_edition_${p.treatment}`)} · {t("nw_evidence")}</summary><p className="my-2">{p.reason}</p><p>{p.evidence.source_file} · {p.evidence.start}–{p.evidence.end}</p><blockquote className="mt-2 border-l-2 pl-3 leading-relaxed whitespace-pre-wrap">{p.original_quote}</blockquote></details>
    </div>)}</div>)}</div>}
  </section>;
}
