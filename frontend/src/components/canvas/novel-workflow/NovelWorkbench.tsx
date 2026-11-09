import { useLocation } from "wouter";
import { refreshAfterWrite } from "@/components/canvas/shared/refreshAfterWrite";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, Loader2, Layers, Upload } from "lucide-react";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { SourceUploadDialog } from "@/components/canvas/episodes/SourceUploadDialog";
import { useActiveResourceIds, useTasksStore } from "@/stores/tasks-store";
import { EPISODE_PLANNING_SLOTS } from "@/actions/generation";
import { errMsg } from "@/utils/async";
import type { ChapterNote, ChapterPreview, NoteEvidence, NovelWorkflow } from "@/types/novel-workflow";

function Evidence({ value }: { value: NoteEvidence }) {
  const { t } = useTranslation("dashboard");
  return <details className="mt-2 text-xs text-muted-foreground">
    <summary className="cursor-pointer">{t("nw_evidence")} · {value.source_file} · {value.start}–{value.end}</summary>
    <blockquote className="mt-2 border-l-2 pl-3 whitespace-pre-wrap">{value.quote}</blockquote>
  </details>;
}

function NoteDetails({ projectName, note }: { projectName: string; note: ChapterNote }) {
  const { t } = useTranslation("dashboard");
  const [source, setSource] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function readSource() {
    setLoading(true); setError("");
    try { setSource((await API.getChapterNoteSource(projectName, note.id)).text); }
    catch (reason) { setError(errMsg(reason)); }
    finally { setLoading(false); }
  }
  const reading = note.reading;
  return <article className="min-w-0 space-y-5 wrap-break-word">
    <header><h2 className="text-lg font-semibold">{note.title}</h2><p className="mt-1 text-xs text-muted-foreground">{note.chars.toLocaleString()} {t("nw_chars")} · {t(`nw_${note.status === "read" ? "read_complete" : note.status ?? "unread"}`)}</p></header>
    <details className="text-sm"><summary className="cursor-pointer">{t("nw_sections")} ({note.sections.length})</summary>{note.sections.map((s) => <p key={`${s.source_file}:${s.start}`} className="mt-1 text-xs text-muted-foreground">{s.title} · {s.start}–{s.end}</p>)}</details>
    {reading ? <>
      <Section title={t("guide_summary")}>{reading.summaries.map((text, i) => <p key={`${i}:${text}`} className="mb-2 leading-relaxed">{text}</p>)}</Section>
      {(["character", "scene", "prop"] as const).map((kind) => <Section key={kind} title={t(`nw_${kind}`)}>
        <div className="grid gap-2">{reading.assets.filter((a) => a.kind === kind).map((a) => <div key={a.id} className="rounded-lg border p-3"><strong>{a.name}</strong>{a.identity_scope && <span className="ml-2 text-xs text-muted-foreground">{a.identity_scope}</span>}<p className="mt-1 leading-relaxed">{a.description}</p><Evidence value={a.evidence} /></div>)}</div>
      </Section>)}
      <Section title={t("guide_changes")}>{reading.changes.map((c) => <div key={c.id} className="mb-3 rounded-lg bg-muted/40 p-3"><strong>{c.character}</strong><p className="mt-1">{c.before} → {c.after}</p><p className="text-xs text-muted-foreground">{c.story_time}</p><Evidence value={c.evidence} /></div>)}</Section>
      <Section title={t("nw_events")}>{reading.events.map((event) => <div key={event.id} className="mb-3 rounded-lg border p-3"><strong>{event.title}</strong><dl className="mt-2 space-y-2">{(["cause", "conflict", "action", "outcome", "open_thread"] as const).map((key) => event[key] && <div key={key}><dt className="inline font-semibold">{t(`nw_${key}`)}：</dt><dd className="inline">{event[key]}</dd></div>)}</dl><Evidence value={event.evidence} />{event.dialogues.map((d) => <blockquote key={d.id} className="mt-2 border-l-2 border-primary/40 pl-3"><strong>{d.speaker}：</strong>{d.quote}</blockquote>)}</div>)}</Section>
      {reading.questions.length > 0 && <Section title={t("nw_questions")}><ul className="list-disc space-y-1 pl-4">{reading.questions.map((q) => <li key={q}>{q}</li>)}</ul></Section>}
    </> : <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">{t("nw_unread_hint")}</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Button variant="outline" size="sm" disabled={loading} onClick={() => source ? setSource(null) : void readSource()}>{loading && <Loader2 className="animate-spin" data-icon="inline-start" />}{t(source ? "nw_hide_source" : "nw_show_source")}</Button>
    {source && <pre className="font-editorial text-sm leading-loose whitespace-pre-wrap wrap-break-word">{source}</pre>}
  </article>;
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="text-sm"><h3 className="mb-2 font-semibold text-foreground">{title}</h3>{children}</section>;
}

export function NovelWorkbench({ projectName, onProduction }: { projectName: string; onProduction: () => void }) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [, navigate] = useLocation();
  const [data, setData] = useState<NovelWorkflow | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<ChapterPreview | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [focused, setFocused] = useState<string | null>(null);
  const [tab, setTab] = useState<"notes" | "svt" | "groups">("notes");
  const [upload, setUpload] = useState(false);
  const [arranging, setArranging] = useState<string | null>(null);
  const [merging, setMerging] = useState(false);
  const [title, setTitle] = useState("");
  const active = useActiveResourceIds("text_episode_plan", projectName);
  const working = EPISODE_PLANNING_SLOTS.some((slot) => active.has(slot));
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const value = await API.getNovelWorkflow(projectName, { signal: controller.signal });
        if (!controller.signal.aborted) setData(value);
      } catch (reason) { if (!controller.signal.aborted) setError(errMsg(reason)); }
      if (!controller.signal.aborted && working) timer = setTimeout(() => void poll(), 3000);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [projectName, revision, working]);
  async function act(work: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true); setError("");
    try { await work(); await useTasksStore.getState().refreshTasks(); setRevision((n) => n + 1); }
    catch (reason) { setError(errMsg(reason)); }
    finally { setBusy(false); }
  }
  const selectedNotes = data?.notes.filter((n) => selected.includes(n.id)) ?? [];
  const note = data?.notes.find((n) => n.id === focused) ?? data?.notes[0];
  const canRun = !!data?.source_basis && selectedNotes.length > 0 && !data.stale && !working && !busy;
  const progress = data?.progress;
  return <div className="flex min-h-0 min-w-0 flex-1 flex-col">
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
      <div><h1 className="font-semibold">{t("dashboard:nw_title")}</h1><p className="mt-1 text-xs text-muted-foreground">{t("dashboard:nw_flow")}</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="ghost" size="sm" onClick={() => setUpload(true)}><Upload data-icon="inline-start" />{t("dashboard:nw_upload")}</Button><Button variant="outline" size="sm" onClick={onProduction}>{t("dashboard:nw_production")}</Button></div>
    </header>
    {error && <p role="alert" className="border-b px-5 py-3 text-sm text-destructive">{error}</p>}
    {working && <div role="status" className="flex shrink-0 flex-wrap items-center gap-3 border-b bg-primary/10 px-5 py-3 text-sm"><Loader2 className="size-4 animate-spin" />{t(progress?.phase === "svt" ? "dashboard:nw_svt_running" : "dashboard:nw_reading_running")} · {progress?.done ?? 0}/{progress?.total ?? selected.length}{progress?.parts ? ` · ${progress.part}/${progress.parts}` : ""}<Button variant="outline" size="sm" disabled={busy} onClick={() => void act(() => API.stopEpisodePlanning(projectName))}>{t("dashboard:nw_stop")}</Button></div>}
    {!working && progress?.error && <details className="border-b px-5 py-2 text-sm text-destructive"><summary>{t("dashboard:nw_last_error")}</summary>{progress.error}</details>}
    {data?.stale && <p className="border-b bg-muted px-5 py-3 text-sm">{t("dashboard:nw_stale")}</p>}
    {!data?.initialized ? <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center"><BookOpen className="size-8 text-primary" /><h2 className="font-semibold">{t("dashboard:nw_start")}</h2><p className="max-w-xl text-sm text-muted-foreground">{t("dashboard:nw_start_hint")}</p><Button disabled={busy || !data} onClick={() => void act(async () => setPreview(await API.previewChapterNotes(projectName)))}>{t("dashboard:nw_preview")}</Button></div> : <>
      <nav aria-label={t("dashboard:nw_title")} className="flex shrink-0 flex-wrap gap-2 border-b px-5 py-2">{(["notes", "svt", "groups"] as const).map((key) => <Button key={key} size="sm" variant={tab === key ? "default" : "ghost"} onClick={() => setTab(key)}>{t(`dashboard:nw_tab_${key}`)} ({key === "notes" ? data.notes.length : key === "svt" ? data.svts.length : data.groups.length})</Button>)}<Button size="sm" variant="ghost" disabled={busy || working} onClick={() => void act(async () => setPreview(await API.previewChapterNotes(projectName)))}>{t("dashboard:nw_preview")}</Button></nav>
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-2">
        <span className="mr-2 text-xs text-muted-foreground">{t("dashboard:nw_selected", { count: selectedNotes.length })}</span>
        <Button size="sm" variant="outline" onClick={() => setSelected(data.notes.map((n) => n.id))}>{t("dashboard:nw_select_all")}</Button>
        <Button size="sm" variant="ghost" onClick={() => setSelected([])}>{t("dashboard:nw_clear")}</Button>
        <Button size="sm" disabled={!canRun} onClick={() => void act(() => API.runNoteWorkflow(projectName, "read", selected, data.source_basis!))}>{t("dashboard:nw_read")}</Button>
        <Button size="sm" variant="outline" disabled={!canRun || selectedNotes.some((n) => n.status !== "read")} onClick={() => void act(() => API.runNoteWorkflow(projectName, "svt", selected, data.source_basis!))}>{t("dashboard:nw_generate_svt")}</Button>
        <Button size="sm" variant="outline" disabled={busy || selectedNotes.length < 2 || data.stale} onClick={() => { setTitle(""); setMerging(true); }}><Layers data-icon="inline-start" />{t("dashboard:nw_merge")}</Button>
      </div>
      {tab === "notes" && <div className="@container/notebook flex min-h-0 min-w-0 flex-1">
        <aside className="relative w-56 shrink-0 overflow-y-auto border-r [scrollbar-gutter:stable] @max-[640px]/notebook:w-36"><ul>{data.notes.map((n) => <li key={n.id} className={`flex items-start gap-2 border-b p-3 ${note?.id === n.id ? "bg-primary/10" : ""}`}><input type="checkbox" aria-label={t("dashboard:nw_select_note", { title: n.title })} checked={selected.includes(n.id)} onChange={(event) => setSelected((prev) => event.target.checked ? [...prev, n.id] : prev.filter((id) => id !== n.id))} className="mt-1" /><button className="focus-ring min-w-0 text-left text-sm wrap-break-word" onClick={() => setFocused(n.id)}><span className="font-semibold">{n.order}. {n.title}</span><span className="mt-1 block text-xs text-muted-foreground">{t(`dashboard:nw_${n.status === "read" ? "read_complete" : n.status ?? "unread"}`)} · {n.chars.toLocaleString()}</span>{n.reading && <span className="block text-xs text-muted-foreground">{t("dashboard:nw_assets_count", { count: n.reading.assets.length })}</span>}{n.needs_review && <span className="block text-xs text-destructive">{t("dashboard:nw_review_heading")}</span>}</button></li>)}</ul></aside>
        <div className="relative min-h-0 min-w-0 flex-1 overflow-y-auto p-5 [scrollbar-gutter:stable]">{note && <NoteDetails key={`${note.id}:${note.basis}`} projectName={projectName} note={note} />}</div>
      </div>}
      {tab === "svt" && <div className="relative min-h-0 flex-1 space-y-4 overflow-y-auto p-5 [scrollbar-gutter:stable]">{data.svt_stale && <p className="text-sm text-destructive">{t("dashboard:nw_svt_stale")}</p>}{data.svts.length === 0 && <p className="text-sm text-muted-foreground">{t("dashboard:nw_svt_empty")}</p>}{data.svts.map((svt, i) => <article key={svt.id} className="rounded-xl border p-4"><h2 className="font-semibold">SVT {i + 1} · {svt.title}</h2><p className="mt-1 text-xs text-muted-foreground">{svt.note_ids.map((id) => data.notes.find((n) => n.id === id)?.title ?? id).join(" / ")}</p>{svt.stale && <p className="text-sm text-destructive">{t("dashboard:nw_svt_stale")}</p>}<p className="my-3 text-sm leading-relaxed">{svt.summary}</p><p className="mb-3 text-sm">{svt.mainline_reason}</p>{(["climaxes", "payoffs"] as const).map((kind) => <Section key={kind} title={t(`dashboard:nw_${kind}`)}>{svt[kind].length ? svt[kind].map((v, j) => <p key={`${j}:${v.description}`} className="mb-2">{v.description} — {v.reason}</p>) : <p className="text-muted-foreground">{t("dashboard:nw_none")}</p>}</Section>)}<Section title={t("dashboard:nw_dialogues")}>{svt.dialogues.map((d) => <blockquote key={d.id} className="my-2 border-l-2 border-primary/40 pl-3"><strong>{d.speaker}：</strong>{d.quote}<Evidence value={d.evidence} /></blockquote>)}</Section><details className="mt-3 text-sm"><summary>{t("dashboard:nw_evidence")}</summary>{svt.evidence.map((e) => <Evidence key={`${e.source_file}:${e.start}:${e.end}`} value={e} />)}</details><Button size="sm" variant="outline" className="mt-3" onClick={() => { setSelected(svt.note_ids); setTab("notes"); }}>{t("dashboard:nw_select_sources")}</Button></article>)}{data.suggestions && data.suggestions.length > 0 && <Section title={t("dashboard:nw_ai_suggestions")}><ul className="list-disc pl-4">{data.suggestions.map((s) => <li key={s}>{s}</li>)}</ul><p className="mt-2 text-muted-foreground">{t("dashboard:nw_manual_only")}</p></Section>}</div>}
      {tab === "groups" && <div className="relative min-h-0 flex-1 space-y-4 overflow-y-auto p-5 [scrollbar-gutter:stable]"><p className="text-sm text-muted-foreground">{t("dashboard:nw_manual_only")}</p>{data.groups.map((group) => <article key={group.id} className="rounded-xl border p-4"><h2 className="font-semibold">{group.title}</h2><ul className="my-2 list-disc pl-5 text-sm">{group.note_ids.map((id) => <li key={id}>{data.notes.find((n) => n.id === id)?.title ?? t("dashboard:nw_missing_note")}</li>)}</ul>{group.source_basis !== data.source_basis && <p className="text-sm text-destructive">{t("dashboard:nw_stale")}</p>}<Button variant="outline" size="sm" disabled={busy || working || data.stale} onClick={() => setArranging(group.id)}>{t("dashboard:nw_arrange_episode")}</Button><Button variant="destructive" size="sm" disabled={busy} onClick={() => void act(() => API.dissolveNoteGroup(projectName, group.id))}>{t("dashboard:nw_dissolve")}</Button></article>)}</div>}
    </>}
    <Dialog open={preview !== null} onOpenChange={(open) => { if (!open && !busy) setPreview(null); }}><DialogContent><DialogTitle>{t("dashboard:nw_preview")}</DialogTitle><DialogDescription>{t("dashboard:nw_preview_hint", { count: preview?.notes.length ?? 0 })}</DialogDescription><div className="relative max-h-80 overflow-y-auto text-sm">{preview?.notes.map((n) => <p key={n.id} className="py-1">{n.order}. {n.title} · {n.sections.length} {t("dashboard:nw_sections")}{n.needs_review && ` · ${t("dashboard:nw_review_heading")}`}</p>)}</div><DialogFooter><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>{t("common:cancel")}</Button><Button disabled={busy || working || !preview} onClick={() => void act(async () => { await API.initializeChapterNotes(projectName, preview!.source_basis); setPreview(null); setSelected([]); })}>{t("dashboard:nw_initialize")}</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={merging} onOpenChange={(open) => { if (!busy) setMerging(open); }}><DialogContent><DialogTitle>{t("dashboard:nw_merge")}</DialogTitle><DialogDescription>{t("dashboard:nw_manual_only")}</DialogDescription><Input aria-label={t("dashboard:nw_group_title")} placeholder={t("dashboard:nw_group_title")} value={title} onChange={(e) => setTitle(e.target.value)} /><ul className="relative max-h-64 list-disc overflow-y-auto pl-5 text-sm">{selectedNotes.map((n) => <li key={n.id}>{n.title}</li>)}</ul><DialogFooter><Button variant="outline" disabled={busy} onClick={() => setMerging(false)}>{t("common:cancel")}</Button><Button disabled={busy || !data?.source_basis} onClick={() => void act(async () => { await API.createNoteGroup(projectName, selected, title, data!.source_basis!); setMerging(false); setTab("groups"); })}>{t("dashboard:nw_confirm_merge")}</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={arranging !== null} onOpenChange={(open) => { if (!open && !busy) setArranging(null); }}><DialogContent><DialogTitle>{t("dashboard:nw_arrange_episode")}</DialogTitle><DialogDescription>{t("dashboard:nw_arrange_hint")}</DialogDescription><p className="text-sm font-semibold">{data?.groups.find((group) => group.id === arranging)?.title}</p><DialogFooter><Button variant="outline" disabled={busy} onClick={() => setArranging(null)}>{t("common:cancel")}</Button><Button disabled={busy || !arranging} onClick={() => void act(async () => { const created = await API.arrangeNoteGroup(projectName, arranging!); setArranging(null); if (await refreshAfterWrite(projectName, t) === "success") navigate(`/episodes/${created.episode}`); })}>{t("common:confirm")}</Button></DialogFooter></DialogContent></Dialog>
    {upload && <SourceUploadDialog projectName={projectName} initialMode="whole_source" onClose={() => { setUpload(false); setRevision((n) => n + 1); }} />}
  </div>;
}
