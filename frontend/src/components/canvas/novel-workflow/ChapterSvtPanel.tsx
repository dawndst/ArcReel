import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { ChapterNote, NoteEvidence, NovelSVT, SVTMoment } from "@/types/novel-workflow";

function Evidence({ values }: { values: NoteEvidence[] }) {
  const { t } = useTranslation("dashboard");
  return <details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">{t("nw_evidence")}</summary>{values.map((e) => <blockquote key={`${e.note_id}:${e.source_file}:${e.start}:${e.end}`} className="mt-2 border-l-2 pl-3 whitespace-pre-wrap"><span className="block text-muted-foreground">{e.source_file} · {e.start}–{e.end}</span>{e.quote}</blockquote>)}</details>;
}

function Moments({ values, note, kind }: { values: SVTMoment[]; note: ChapterNote; kind: "climaxes" | "payoffs" }) {
  const { t } = useTranslation("dashboard");
  const noteId = note.id;
  return <section className="space-y-3 rounded-xl border bg-card p-5"><h3 className="text-base font-bold">{t(`nw_chapter_${kind}`)} · {values.length}</h3>{values.length ? values.map((m, i) => {
    const shared = m.note_ids.some((id) => id !== noteId);
    const localEvents = note.reading?.events.filter((e) => m.event_ids?.includes(e.id)) ?? [];
    const scene = shared ? localEvents.map((e) => `${e.title}：${e.action}；${e.outcome}`).join("\n") || t("nw_chapter_shared_scene") : m.scene;
    return <article key={i} className="space-y-3 rounded-lg border bg-muted/15 p-4">
      {shared && <p className="text-xs font-semibold text-warn">{t("nw_chapter_shared_moment")}</p>}
      <p className="whitespace-pre-wrap leading-7">{scene}</p>{!shared && <p className="text-xs text-muted-foreground">{m.reason}</p>}
      <div className="space-y-2"><h4 className="text-sm font-bold">{t("nw_chapter_dialogues")}</h4>{m.dialogues.filter((d) => d.evidence.note_id === noteId).map((d) => <blockquote key={d.id} className="rounded-r border-l-2 border-primary/40 bg-primary/5 p-3 leading-7"><strong>{d.speaker}：</strong>{d.quote}<Evidence values={[d.evidence]} /></blockquote>)}</div>
      <Evidence values={m.evidence.filter((e) => e.note_id === noteId)} />
    </article>;
  }) : <p className="text-sm text-muted-foreground">{t("nw_none")}</p>}</section>;
}

export function ChapterSvtPanel({ notes, svts, noteId, select, sources }: {
  notes: ChapterNote[]; svts: NovelSVT[]; noteId?: string;
  select: (id: string) => void; sources: (ids: string[]) => void;
}) {
  const { t } = useTranslation("dashboard");
  const note = notes.find((n) => n.id === noteId);
  const svt = svts.find((s) => !s.stale && s.note_ids.includes(noteId ?? ""));
  const story = svt?.note_stories?.[noteId ?? ""];
  const climaxes = svt?.climaxes.filter((m) => m.note_ids.includes(noteId ?? "")) ?? [];
  const payoffs = svt?.payoffs.filter((m) => m.note_ids.includes(noteId ?? "")) ?? [];
  return <div className="space-y-4">
    <label className="flex flex-wrap items-center gap-3 text-sm font-semibold">{t("nw_chapter_svt_source")}<select aria-label={t("nw_chapter_svt_source")} value={note?.id ?? ""} onChange={(e) => select(e.target.value)} className="max-w-full rounded border border-input bg-background p-2">{notes.map((n) => <option key={n.id} value={n.id}>{n.order}. {n.title}</option>)}</select></label>
    {!svt || !note ? <p className="text-sm text-muted-foreground">{t("nw_svt_empty")}</p> : <article id={`svt-${svt.id}`} className="space-y-4">
      <header className="space-y-3 rounded-xl border border-primary/30 bg-card p-5"><p className="text-xs font-semibold text-primary">{note?.title} · {t("nw_chapter_svt")}</p><h2 className="text-xl font-bold leading-8">{story?.title ?? t("nw_chapter_story_missing")}</h2>{story && <><p className="whitespace-pre-wrap text-base leading-8">{story.summary}</p><section className="rounded-lg bg-primary/5 p-3"><h3 className="mb-1 text-sm font-bold">{t("nw_chapter_advancement")}</h3><p className="text-sm leading-7">{story.advancement}</p></section></>}<p className="text-xs font-semibold">{t("nw_svt_counts", { climaxes: climaxes.length, payoffs: payoffs.length })}</p></header>
      <Moments values={climaxes} note={note!} kind="climaxes" /><Moments values={payoffs} note={note!} kind="payoffs" />
      <details className="space-y-3 rounded-xl border bg-muted/15 p-5"><summary className="cursor-pointer font-semibold">{t("nw_chapter_mainline")} · {svt.title}</summary><p className="text-xs text-muted-foreground">{t("nw_chapter_mainline_hint")}</p><p className="text-sm">{svt.note_ids.map((id) => notes.find((n) => n.id === id)?.title ?? id).join(" / ")}</p><p className="whitespace-pre-wrap text-sm leading-7">{svt.summary}</p><p className="text-sm text-muted-foreground">{svt.mainline_reason}</p><Button size="sm" variant="outline" onClick={() => sources(svt.note_ids)}>{t("nw_select_sources")}</Button></details>
    </article>}
  </div>;
}
