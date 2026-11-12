import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { errMsg } from "@/utils/async";
import { sourceExcerptDisplay } from "@/utils/source-excerpt";

export function NoteSourcePanel({ projectName, noteId }: { projectName: string; noteId: string }) {
  const { t } = useTranslation("dashboard");
  const [source, setSource] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    void API.getChapterNoteSource(projectName, noteId).then((value) => { if (active) { setSource(value.text); setError(""); } }).catch((reason: unknown) => { if (active) setError(errMsg(reason)); });
    return () => { active = false; };
  }, [projectName, noteId, attempt]);
  return <section className="rounded-xl border bg-card p-5">
    {source === null && !error && <p role="status" className="text-sm text-muted-foreground">{t("nw_note_text_loading")}</p>}
    {error && <div className="space-y-3"><p role="alert" className="text-sm text-destructive">{error}</p><Button size="sm" variant="outline" onClick={() => setAttempt((n) => n + 1)}>{t("nw_note_text_retry")}</Button></div>}
    {source !== null && <p className="font-editorial text-base leading-8 whitespace-pre-wrap wrap-break-word">{sourceExcerptDisplay(source)}</p>}
  </section>;
}
