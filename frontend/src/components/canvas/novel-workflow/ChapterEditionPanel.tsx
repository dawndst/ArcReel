import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { errMsg } from "@/utils/async";
import type { ChapterEdition, ChapterNote } from "@/types/novel-workflow";

export function ChapterEditionPanel({ projectName, note, disabled, generate }: { projectName: string; note: ChapterNote; disabled: boolean; generate: () => void }) {
  const { t } = useTranslation("dashboard");
  const [value, setValue] = useState<ChapterEdition | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const basis = note.edition?.basis;
  useEffect(() => {
    if (!basis) return;
    let active = true;
    void API.getChapterEdition(projectName, note.id).then((edition) => { if (active) { setValue(edition); setError(""); } }).catch((reason: unknown) => { if (active) setError(errMsg(reason)); });
    return () => { active = false; };
  }, [projectName, note.id, basis, attempt]);
  return <section className="space-y-4 rounded-xl border bg-card p-5">
    {!basis && <><p className="text-sm text-muted-foreground">{t(note.reading ? "nw_note_edition_empty" : "nw_note_edition_prerequisite")}</p><Button size="sm" variant="outline" disabled={disabled || !note.reading} onClick={generate}>{t("nw_note_edition_generate")}</Button></>}
    {basis && !value && !error && <p role="status" className="text-sm text-muted-foreground">{t("nw_note_text_loading")}</p>}
    {error && <div className="space-y-3"><p role="alert" className="text-sm text-destructive">{error}</p><Button size="sm" variant="outline" onClick={() => setAttempt((n) => n + 1)}>{t("nw_note_text_retry")}</Button></div>}
    {value && <div className="space-y-5">{value.parts.map((part, i) => <div key={i} className="space-y-4">{part.passages.map((p) => <div key={p.unit} className="space-y-2 text-sm">
      {p.text && <p className="text-base leading-8 whitespace-pre-wrap">{p.text}</p>}
      <details className="rounded border bg-muted/20 p-2 text-xs text-muted-foreground"><summary className="cursor-pointer">{t(`nw_edition_${p.treatment}`)} · {t("nw_evidence")}</summary><p className="my-2">{p.reason}</p><p>{p.evidence.source_file} · {p.evidence.start}–{p.evidence.end}</p><blockquote className="mt-2 border-l-2 pl-3 leading-relaxed whitespace-pre-wrap">{p.original_quote}</blockquote></details>
    </div>)}</div>)}</div>}
  </section>;
}
