import { sceneLibraryOrder } from "./scene-library-order";
import { SceneBatchSource, type SourceTarget } from "./SceneBatchSource";
import { AssetIdentityResolver, type IdentityDecision } from "./AssetIdentityResolver";
import { workflowProgress } from "./workflow-progress";
import { ReadingQuestions } from "./ReadingAnnotations";
import { NoteSourcePanel } from "./NoteSourcePanel";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { ChapterEditionPanel } from "./ChapterEditionPanel";
import { NoteProductionActions, noteProductionStatus } from "./NoteProductionActions";
import { useProjectsStore } from "@/stores/projects-store";
import { ClaimBadge } from "./ClaimBadge";
import { NoteReadingRange } from "./NoteReadingStart";
import { NoteGroupsPanel } from "./NoteGroupsPanel";
import { DeliveryPanel } from "./DeliveryPanel";
import type { ExecutionAssetOption } from "@/types/novel-workflow";
import { SceneLibraryPanel } from "./SceneLibraryPanel";
import { ReadingScopePanel } from "./ReadingScopePanel";
import { useAppStore } from "@/stores/app-store";
import { CrossChapterPanel, ReadingSettings } from "./CrossChapterPanel";
import { ReadingEnrichment, LedgerPanel, ReviewPanel } from "./UnderstandingPanels";
import { useLocation, useSearch } from "wouter";
import { refreshAfterWrite } from "@/components/canvas/shared/refreshAfterWrite";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, Loader2, Layers, Upload } from "lucide-react";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { SourceUploadDialog } from "@/components/canvas/episodes/SourceUploadDialog";
import { isResourceBusy, useActiveResourceIds, useTasksStore } from "@/stores/tasks-store";
import { NOVEL_WORKFLOW_SLOTS } from "@/actions/generation";
import { errMsg } from "@/utils/async";
import type { ChapterNote, ChapterPreview, NoteEvidence, NovelWorkflow } from "@/types/novel-workflow";

function Evidence({ value }: { value: NoteEvidence }) {
  const { t } = useTranslation("dashboard");
  return <details className="mt-2 text-xs text-muted-foreground">
    <summary className="cursor-pointer">{t("nw_evidence")} · {value.source_file} · {value.start}–{value.end}</summary>
    <blockquote className="mt-2 border-l-2 pl-3 whitespace-pre-wrap">{value.quote}</blockquote>
  </details>;
}

function PrimarySvt({ note, busy, adopt }: { note: ChapterNote; busy: boolean; adopt: (candidate: string) => void }) {
  const { t } = useTranslation("dashboard");
  return (
    <section className="space-y-3 rounded-xl border border-primary/20 bg-primary/5 p-5"><h3 className="text-xs font-bold text-primary">{t("nw_note_primary_svt")}</h3><p className="text-lg font-semibold leading-relaxed">{note.svt_title ?? t("nw_svt_unassigned")}</p>{note.svt_id && <p className="text-xs text-muted-foreground">{t(note.svt_status === "complete" ? "nw_svt_complete" : "nw_svt_needs_details")}</p>}
      {!!note.svt_candidates?.length && <details className="border-t border-primary/15 pt-3"><summary className="cursor-pointer text-xs font-medium text-muted-foreground">{t("nw_svt_candidates")} ({note.svt_candidates?.length ?? 0})</summary>
      {(note.svt_candidates ?? []).map((candidate) => <article key={candidate.candidate_id} className="space-y-2 rounded border p-3 text-sm"><strong>{candidate.title}</strong><p>{candidate.summary}</p><p className="text-muted-foreground">{candidate.reason}</p><Button size="sm" variant="outline" disabled={busy} onClick={() => adopt(candidate.candidate_id)}>{t("nw_svt_adopt")}</Button></article>)}
      </details>}
    </section>
  );
}

function NoteDetails({ projectName, note, busy, adopt, condense, resolveAsset }: { projectName: string; note: ChapterNote; busy: boolean; adopt: (candidate: string) => void; condense: () => void; resolveAsset: (id: string, value: IdentityDecision) => Promise<void> }) {
  const { t } = useTranslation("dashboard");
  const [_location, navigate] = useLocation();
  const [view, setView] = useState("info");
  const reading = note.reading;
  return <article className="min-w-0 space-y-5 wrap-break-word">
    <header className="space-y-2 border-b pb-5"><h2 className="text-2xl font-bold tracking-tight">{note.title}</h2><div className="flex flex-wrap items-start gap-x-4 gap-y-2 text-xs text-muted-foreground"><p>{note.chars.toLocaleString()} {t("nw_chars")} · {t(`nw_${note.status === "read" ? "read_complete" : note.status ?? "unread"}`)}</p><details><summary className="cursor-pointer">{t("nw_sections")} ({note.sections.length})</summary>{note.sections.map((s) => <p key={`${s.source_file}:${s.start}`} className="mt-2">{s.title} · {s.start}–{s.end}</p>)}</details></div></header>
    {note.in_scope === false && <p className="rounded border border-warn/30 bg-warn/5 p-3 text-sm">{t("nw_scope_browse_only")}</p>}
    <Tabs value={view} onValueChange={(next) => setView(next as string)}>
      <div className="rounded-lg border bg-card p-1"><div className="relative overflow-x-auto"><TabsList className="w-full min-w-max" aria-label={t("nw_note_views")}><TabsTrigger value="info">{t("nw_note_tab_info")}</TabsTrigger><TabsTrigger value="source">{t("nw_note_tab_source")}</TabsTrigger><TabsTrigger value="edition">{t("nw_note_tab_edition")}</TabsTrigger></TabsList></div></div>
      <TabsContent value="info"><div className="space-y-5 pt-3">
    {!reading && <PrimarySvt note={note} busy={busy || note.in_scope === false} adopt={adopt} />}
    {reading ? <>
      <Section title={t("nw_chapter_summary")} featured>{(reading.overview ? [reading.overview.summary] : reading.summaries).map((text, i) => <p key={`${i}:${text}`} className="mb-2 text-base leading-8">{text}</p>)}</Section>
      <PrimarySvt note={note} busy={busy || note.in_scope === false} adopt={adopt} />
      {reading.overview && <Section title={t("nw_chapter_causality")}><dl className="space-y-2">{(["cause", "conflict", "action", "outcome"] as const).map((key) => <div key={key}><dt className="mr-1 text-xs font-bold text-muted-foreground">{t(`nw_${key}`)}：</dt><dd className="inline leading-7">{reading.overview![key]}</dd></div>)}</dl><p className="mt-2">{reading.overview.hook}</p></Section>}
      <ReadingEnrichment note={note} />
      {(["character", "scene", "prop"] as const).map((kind) => <Section key={kind} title={t(`nw_${kind}`)}>
        <div className="grid gap-2">{reading.assets.filter((a) => a.kind === kind).map((a) => <div key={a.id} className="rounded-lg border border-border/60 bg-muted/20 p-4"><button type="button" disabled={!a.asset_name || a.asset_missing} title={`${a.description}
${a.evidence.source_file}
${a.evidence.quote}`} className="font-semibold text-primary underline decoration-dotted underline-offset-4 disabled:text-muted-foreground disabled:no-underline" onClick={() => {
          const route = `/${{ character: "characters", scene: "scenes", prop: "props" }[a.kind]}`;
          useAppStore.getState().triggerScrollTo({ type: a.kind, id: a.asset_name!, route });
          navigate(`/app/projects/${encodeURIComponent(projectName)}${route}`);
        }}>{a.asset_code && <span className="mr-2 rounded border bg-card px-1.5 py-0.5 font-mono text-xs font-medium text-muted-foreground">{a.asset_code}</span>}{a.asset_name || a.name}{a.variant && ` / ${a.variant}`}</button>{a.identity_scope && <span className="ml-2 text-xs text-muted-foreground">{a.identity_scope}</span>}<p className="mt-2 leading-7">{a.description}</p><Evidence value={a.evidence} />{a.state && <p className="mt-2 text-xs text-muted-foreground">{t("nw_asset_state")}：{a.state}</p>}{a.performance && <p className="mt-2 text-xs text-muted-foreground">{t("nw_asset_performance")}：{a.performance}</p>}{a.asset_issue && <AssetIdentityResolver key={`${a.id}:${a.asset_issue}`} asset={a} disabled={busy || note.in_scope === false} save={(value) => resolveAsset(a.id, value)} />}</div>)}</div>
      </Section>)}
      <Section title={t("guide_changes")}>{reading.changes.map((c) => <div key={c.id} className="mb-3 rounded-lg bg-muted/40 p-3"><strong>{c.character}</strong><ClaimBadge value={c} /><p className="mt-1">{c.before} → {c.after}</p><p className="text-xs text-muted-foreground">{c.story_time}</p><Evidence value={c.evidence} /></div>)}</Section>
      <Section title={t("nw_events")}>{reading.events.map((event) => <div key={event.id} className="mb-4 rounded-lg border bg-muted/15 p-4"><strong className="text-base">{event.title}</strong><ClaimBadge value={event} /><dl className="mt-2 space-y-2">{(["cause", "conflict", "action", "outcome", "open_thread"] as const).map((key) => event[key] && <div key={key}><dt className="mr-1 text-xs font-bold text-muted-foreground">{t(`nw_${key}`)}：</dt><dd className="inline leading-7">{event[key]}</dd></div>)}</dl><Evidence value={event.evidence} />{event.dialogues.map((d) => <blockquote key={d.id} className="mt-3 rounded-r-lg border-l-2 border-primary/40 bg-primary/5 p-3 leading-7"><strong>{d.speaker}：</strong>{d.quote}</blockquote>)}</div>)}</Section>
      <ReadingQuestions reading={reading} />
    </> : <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">{t("nw_unread_hint")}</p>}
      </div></TabsContent>
      <TabsContent value="source"><div className="pt-3"><NoteSourcePanel projectName={projectName} noteId={note.id} /></div></TabsContent>
      <TabsContent value="edition"><div className="pt-3"><ChapterEditionPanel key={note.edition?.basis ?? "missing"} projectName={projectName} note={note} disabled={busy || note.in_scope === false} generate={condense} /></div></TabsContent>
    </Tabs>
  </article>;
}

function Section({ title, children, featured = false }: { title: string; children: ReactNode; featured?: boolean }) {
  return <section className={`rounded-xl border bg-card p-5 text-sm shadow-xs ${featured ? "border-primary/25" : "border-border"}`}><h3 className={`mb-4 border-b pb-3 text-base font-bold ${featured ? "text-primary" : "text-foreground"}`}>{title}</h3>{children}</section>;
}

const WORKBENCH_TABS = ["notes", "svt", "groups", "ledger", "review", "understanding", "scenes"] as const;
type WorkbenchTab = typeof WORKBENCH_TABS[number];

export function NovelWorkbench({ projectName }: { projectName: string }) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [location, navigate] = useLocation();
  const project = useProjectsStore((state) => state.currentProjectData);
  const [data, setData] = useState<NovelWorkflow | null>(null);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<ChapterPreview | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const search = useSearch();
  const requestedNote = new URLSearchParams(search).get("note");
  const [focused, setFocused] = useState<string | null>(requestedNote);
  const [tab, setTabState] = useState<WorkbenchTab>(() => {
    const requested = new URLSearchParams(search).get("workbench") as WorkbenchTab;
    return WORKBENCH_TABS.includes(requested) ? requested : "notes";
  });
  function setTab(next: WorkbenchTab, shot?: string) {
    setTabState(next);
    const params = new URLSearchParams(search);
    params.set("workbench", next);
    if (shot) params.set("shot", shot);
    else if (next !== "scenes") params.delete("shot");
    navigate(`${location}?${params.toString()}`, { replace: true });
  }
  const requestedShot = new URLSearchParams(search).get("shot");
  useEffect(() => {
    if (tab === "scenes" && requestedShot && data) requestAnimationFrame(() => document.getElementById(`library-shot-${requestedShot}`)?.scrollIntoView({ block: "center" }));
  }, [tab, requestedShot, data]);
  const [focusedBatch, setFocusedBatch] = useState<string | null>(null);
  useEffect(() => { if (tab === "scenes" && focusedBatch) document.getElementById(`scene-batch-${focusedBatch}`)?.scrollIntoView({ block: "start" }); }, [tab, focusedBatch]);
  const [focusedSvt, setFocusedSvt] = useState<string | null>(null);
  useEffect(() => { if (tab === "svt" && focusedSvt) document.getElementById(`svt-${focusedSvt}`)?.scrollIntoView({ block: "start" }); }, [tab, focusedSvt]);
  const [readingSettings, setReadingSettings] = useState(false);
  const [upload, setUpload] = useState(false);
  const [sourceBatch, setSourceBatch] = useState<SourceTarget | null>(null);
  const [shotSelection, setShotSelection] = useState<string[]>([]);
  const [episodeTitle, setEpisodeTitle] = useState("");
  const [assemblyRequest, setAssemblyRequest] = useState(() => crypto.randomUUID());

  const [merging, setMerging] = useState(false);
  const [title, setTitle] = useState("");
  const active = useActiveResourceIds("text_novel_workflow", projectName);
  const working = NOVEL_WORKFLOW_SLOTS.some((slot) => active.has(slot));
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
  const assetOptions: ExecutionAssetOption[] = [
    ...Object.entries(project?.characters ?? {}).flatMap(([name, item]) => [{ kind: "character" as const, name, asset_code: item.asset_code ?? "" }, ...Object.entries(item.derivatives ?? {}).map(([variant, derivative]) => ({ kind: "character" as const, name: `${name}/${variant}`, asset_code: derivative.asset_code ?? item.asset_code ?? "" }))]),
    ...Object.entries(project?.scenes ?? {}).map(([name, item]) => ({ kind: "scene" as const, name, asset_code: item.asset_code ?? "" })),
    ...Object.entries(project?.props ?? {}).map(([name, item]) => ({ kind: "prop" as const, name, asset_code: item.asset_code ?? "" })),
  ];
  function openAsset(kind: "character" | "scene" | "prop", name: string) {
    const route = `/${{ character: "characters", scene: "scenes", prop: "props" }[kind]}`;
    useAppStore.getState().triggerScrollTo({ type: kind, id: name, route });
    navigate(`/app/projects/${encodeURIComponent(projectName)}${route}`);
  }
  function assembleSelection() { void act(async () => {
    const created = await API.assembleDirectorEpisode(projectName, shotSelection, episodeTitle, data!.source_basis!, assemblyRequest);
    const refreshed = await refreshAfterWrite(projectName, t);
    setRevision((n) => n + 1);
    setAssemblyRequest(crypto.randomUUID());
    if (refreshed === "success") navigate(`/episodes/${created.episode}`);
  }); }
  const selectedNotes = data?.notes.filter((n) => selected.includes(n.id)) ?? [];
  const note = data?.notes.find((n) => n.id === (focused ?? requestedNote)) ?? data?.notes[0];
  const canRead = !!data?.source_basis && selectedNotes.length > 0 && !data.stale && !working && !busy;
  const canRun = canRead && selectedNotes.every((n) => n.in_scope !== false);
  const understoodIds = new Set(data?.understanding?.reports.filter((r) => !r.stale).flatMap((r) => r.selected_note_ids) ?? []);
  const needsUnderstanding = data?.settings?.understanding_enabled !== false && selectedNotes.some((n) => !understoodIds.has(n.id));
  const needsConclusions = data?.settings?.conclusions_enabled !== false && selectedNotes.some((n) => !n.reading?.conclusion_review);
  const blockingConclusions = data?.settings?.conclusions_enabled !== false && selectedNotes.some((n) => n.reading?.conclusion_review?.conclusions.some((c) => c.blocking));
  const needsSvtReview = selectedNotes.some((n) => n.svt_status === "needs_review");
  const referenceOnly = data?.groups.some((g) => g.usage === "reference" && g.note_ids.some((id) => selected.includes(id)));
  const outputStatus = noteProductionStatus(data, selectedNotes);
  const nextStep = selectedNotes.length === 0 ? "nw_next_select"
    : selectedNotes.some((n) => n.in_scope === false) ? "nw_scope_add_first"
    : selectedNotes.some((n) => n.status !== "read") ? "nw_next_read"
    : needsUnderstanding ? "nw_understanding_required"
    : needsConclusions ? "nw_conclusions_pending"
    : blockingConclusions ? "nw_conclusions_blocking"
    : selectedNotes.some((n) => !n.svt_id) ? "nw_next_svt"
    : needsSvtReview ? "nw_svt_review_required"
    : referenceOnly ? "nw_reference_block"
    : outputStatus.batches.length ? outputStatus.scenesStale ? "nw_next_update_scenes" : !outputStatus.scenesForAll ? "nw_next_partial_scenes" : "nw_next_review_assemble"
    : "nw_next_scenes";
  const progress = data?.progress;
  const progressView = workflowProgress(progress ?? null);
  const renderNotes = (items: ChapterNote[]) => <ul>{items.map((n) => <li key={n.id} className={`flex items-start gap-2 border-b border-l-4 p-3 ${note?.id === n.id ? "border-l-primary bg-primary/10" : "border-l-transparent hover:bg-muted/50"}`}><input type="checkbox" aria-label={t("dashboard:nw_select_note", { title: n.title })} checked={selected.includes(n.id)} onChange={(event) => setSelected((prev) => event.target.checked ? [...prev, n.id] : prev.filter((id) => id !== n.id))} className="mt-1" /><button className="focus-ring min-w-0 text-left text-sm wrap-break-word" onClick={() => setFocused(n.id)}><span className={`font-semibold ${n.in_scope === false ? "text-muted-foreground line-through" : ""}`}>{n.order}. {n.title}</span><span className="mt-1 block text-xs text-muted-foreground">{n.in_scope === false ? t(n.reading ? "dashboard:nw_scope_outside_saved" : "dashboard:nw_scope_outside") : t(`dashboard:nw_${n.status === "read" ? "read_complete" : n.status ?? "unread"}`)} · {n.chars.toLocaleString()}</span>{n.reading && <span className="block text-xs text-muted-foreground">{t("dashboard:nw_assets_count", { count: n.reading.assets.length })}</span>}{n.needs_review && <span className="block text-xs text-destructive">{t("dashboard:nw_review_heading")}</span>}</button></li>)}</ul>;
  return <div className="flex min-h-0 min-w-0 flex-1 flex-col">
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b bg-card px-5 py-3">
      <div className="flex min-w-0 flex-1 items-center gap-3"><h1 className="shrink-0 text-lg font-bold tracking-tight">{t("dashboard:nw_title")}{data?.initialized && <span className="ml-2 text-sm font-medium text-muted-foreground">({data.notes.filter((note) => !!note.reading || note.status === "read").length}/{data.notes.length})</span>}</h1><Button variant="outline" size="sm" className="shrink-0" disabled={working || busy} onClick={() => setReadingSettings(true)}>{t("dashboard:nw_read_settings")}</Button><p className="min-w-0 truncate text-xs text-muted-foreground" title={t("dashboard:nw_flow")}>{t("dashboard:nw_flow")}</p></div>
      <div className="flex flex-wrap gap-2"><Button variant="ghost" size="sm" onClick={() => setUpload(true)}><Upload data-icon="inline-start" />{t("dashboard:nw_upload")}</Button></div>
    </header>
    {data?.initialized && <div className="flex shrink-0 flex-wrap gap-3 border-b bg-muted/30 px-5 py-2 text-xs text-muted-foreground"><span>{t("dashboard:nw_calls_limit")}：{data.settings?.max_model_calls ?? 100}</span>{data.call_budget && <span>{t("dashboard:nw_calls_usage", {used:data.call_budget.used, limit:data.call_budget.limit})}</span>}{data.call_budget?.limit_reached && <strong className="text-destructive">{t("dashboard:nw_calls_stopped")}</strong>}</div>}
    {error && <p role="alert" className="border-b px-5 py-3 text-sm text-destructive">{error}</p>}
    {working && <div role="status" className="flex shrink-0 flex-wrap items-center gap-3 border-b bg-primary/10 px-5 py-3 text-sm"><Loader2 className="size-4 animate-spin" />{t(`dashboard:${progressView.label}`)}{progressView.showCounts && <> · {progress?.done ?? 0}/{progress?.total ?? 0}{progress?.parts ? ` · ${progress.part}/${progress.parts}` : ""}</>}<Button variant="outline" size="sm" disabled={busy} onClick={() => void act(() => API.stopNoteWorkflow(projectName))}>{t("dashboard:nw_stop")}</Button></div>}
    {!working && progress?.error && <details className={`border-b px-5 py-2 text-sm ${progress.phase === "stopped" ? "text-muted-foreground" : "text-destructive"}`}><summary>{t(progress.phase === "stopped" ? "dashboard:nw_task_stopped" : "dashboard:nw_last_error")}</summary>{progress.error}</details>}
    {data?.stale && <p className="border-b bg-muted px-5 py-3 text-sm">{t("dashboard:nw_stale")}</p>}
    {!data?.initialized ? <div className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center"><BookOpen className="size-8 text-primary" /><h2 className="font-semibold">{t("dashboard:nw_start")}</h2><p className="max-w-xl text-sm text-muted-foreground">{t("dashboard:nw_start_hint")}</p><Button disabled={busy || !data} onClick={() => void act(async () => setPreview(await API.previewChapterNotes(projectName)))}>{t("dashboard:nw_preview")}</Button></div> : <>
      <nav aria-label={t("dashboard:nw_title")} className="flex shrink-0 flex-wrap gap-2 border-b px-5 py-2">{(["notes", "groups", "ledger", "understanding", "svt", "review", "scenes"] as const).map((key) => <Button key={key} size="sm" variant={tab === key ? "default" : "ghost"} onClick={() => setTab(key)}>{t(`dashboard:nw_tab_${key}`)} ({key === "scenes" ? (data.scene_batches ?? []).reduce((n, b) => n + b.scenes.length, 0) : key === "notes" ? data.notes.length : key === "svt" ? data.svts.length : key === "understanding" ? data.understanding?.links.length ?? 0 : key === "ledger" ? data.ledger?.characters.length ?? 0 : key === "review" ? data.reviews?.length ?? 0 : data.groups.length})</Button>)}<Button size="sm" variant="ghost" disabled={busy || working} onClick={() => void act(async () => setPreview(await API.previewChapterNotes(projectName)))}>{t("dashboard:nw_preview")}</Button></nav>
      {tab === "notes" && <>
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-5 py-2">
        <span className="mr-2 text-xs text-muted-foreground">{t("dashboard:nw_selected", { count: selectedNotes.length })}</span>
        <Button size="sm" variant="outline" onClick={() => setSelected(data.notes.map((n) => n.id))}>{t("dashboard:nw_select_all")}</Button>
        <Button size="sm" variant="ghost" onClick={() => setSelected([])}>{t("dashboard:nw_clear")}</Button>
        <div className="flex max-w-full flex-wrap items-center gap-2"><Button size="sm" disabled={!canRead} onClick={() => void act(() => API.runNoteWorkflow(projectName, "read", selected, data.source_basis!))}>{t("dashboard:nw_read")} · {t("dashboard:nw_selected", { count: selected.length })}</Button>
        <Button size="sm" variant="outline" title={t("dashboard:nw_understand_single_hint")} disabled={!canRun || data.settings?.understanding_enabled === false || selectedNotes.some((n) => n.status !== "read")} onClick={() => void act(async () => { await API.runNoteWorkflow(projectName, "understand", selected, data.source_basis!); setTab("understanding"); })}>{t("dashboard:nw_understand")}</Button></div>
        {data.settings?.conclusions_enabled !== false && <Button size="sm" variant="outline" disabled={!canRun || selectedNotes.some((n) => n.status !== "read")} onClick={() => void act(async () => { if (NOVEL_WORKFLOW_SLOTS.some((slot) => isResourceBusy("text_novel_workflow", projectName, slot))) return; await API.runNoteWorkflow(projectName, "conclusions", selected, data.source_basis!); setTab("understanding"); })}>{t("dashboard:nw_conclusions_run")}</Button>}
        <NoteProductionActions data={data} notes={selectedNotes} busy={busy || working}
          canSvt={canRun && !needsConclusions && !blockingConclusions && !needsUnderstanding && !selectedNotes.some((n) => n.status !== "read")}
          canScenes={canRun && !needsConclusions && !blockingConclusions && !needsUnderstanding && !selectedNotes.some((n) => n.status !== "read" || !n.svt_id) && !needsSvtReview && !referenceOnly}
          viewSvt={(id) => { setFocusedSvt(id); setTab("svt"); }}
          viewScenes={(id) => { setFocusedBatch(id); setTab("scenes"); }}
          run={async (action, ids) => {
            if (busy || working || NOVEL_WORKFLOW_SLOTS.some((slot) => isResourceBusy("text_novel_workflow", projectName, slot))) return;
            await act(async () => { await API.runNoteWorkflow(projectName, action, ids, data.source_basis!); setTab(action === "svt" ? "svt" : "scenes"); });
          }} />
        <Button size="sm" variant="outline" disabled={!canRun || needsUnderstanding || selectedNotes.some((n) => n.status !== "read")} onClick={() => void act(async () => { await API.runNoteWorkflow(projectName, "review", selected, data.source_basis!); setTab("review"); })}>{t("dashboard:nw_review")}</Button>
        <Button size="sm" variant="outline" disabled={busy || selectedNotes.length < 1 || data.stale} onClick={() => { setTitle(""); setMerging(true); }}><Layers data-icon="inline-start" />{t("dashboard:nw_merge")}</Button>
      </div>
      {!working && <div role="status" className="shrink-0 space-y-1 border-b px-5 py-1 text-xs text-muted-foreground"><p>{t(`dashboard:${nextStep}`)}</p>{selectedNotes.some((n) => n.svt_status === "needs_details") && <p className="text-warn">{t("dashboard:nw_svt_incomplete_hint")}</p>}</div>}
      </>}
      {tab === "notes" && <div className="@container/notebook flex min-h-0 min-w-0 flex-1">
        <aside className="relative w-56 shrink-0 overflow-y-auto border-r [scrollbar-gutter:stable] @max-[640px]/notebook:w-36">{data.groups.map((group) => <details key={group.id} className="border-b p-2"><summary className="cursor-pointer text-sm font-semibold">{group.title} ({group.note_ids.length})</summary>{renderNotes(data.notes.filter((n) => group.note_ids.includes(n.id)))}</details>)}{renderNotes(data.notes.filter((n) => !data.groups.some((g) => g.note_ids.includes(n.id))))}</aside>
        <div className="relative min-h-0 min-w-0 flex-1 overflow-y-auto bg-muted/20 p-5 [scrollbar-gutter:stable]">{note && <NoteDetails key={`${note.id}:${note.basis}`} projectName={projectName} note={note} busy={busy || working} resolveAsset={async (id, values) => { if (busy || working) return; await act(async () => { await API.resolveNoteAsset(projectName, id, { ...values, source_basis: data.source_basis!, reading_basis: note.reading!.basis }); await refreshAfterWrite(projectName, t); }); }} condense={() => void act(() => API.runNoteWorkflow(projectName, "condense", [note.id], data.source_basis!))} adopt={(candidate) => void act(() => API.adoptNoteSVT(projectName, note.id, candidate, data.source_basis!))} />}</div>
      </div>}
      {tab === "svt" && <div className="relative min-h-0 flex-1 space-y-4 overflow-y-auto p-5 [scrollbar-gutter:stable]">{data.svt_stale && <p className="text-sm text-destructive">{t("dashboard:nw_svt_stale")}</p>}{data.svts.length === 0 && <p className="text-sm text-muted-foreground">{t("dashboard:nw_svt_empty")}</p>}{data.svts.map((svt, i) => <article key={svt.id} id={`svt-${svt.id}`} className="rounded-xl border bg-card p-5 shadow-xs"><h2 className="font-semibold">SVT {i + 1} · {svt.title}</h2><p className="mt-1 text-xs text-muted-foreground">{svt.note_ids.map((id) => data.notes.find((n) => n.id === id)?.title ?? id).join(" / ")}</p>{svt.stale && <p className="text-sm text-destructive">{t("dashboard:nw_svt_stale")}</p>}<p className="my-3 text-sm leading-relaxed">{svt.summary}</p><p className="mb-2 text-xs text-muted-foreground">{t(svt.breakdown_status === "complete" ? "dashboard:nw_svt_complete" : "dashboard:nw_svt_needs_details")}</p><p className="mb-2 text-xs font-semibold">{t("dashboard:nw_svt_counts", { climaxes: svt.climaxes.length, payoffs: svt.payoffs.length })}</p>{svt.breakdown_status !== "complete" && <p className="mb-3 rounded border border-warn/40 bg-warn/10 p-3 text-sm">{t(svt.breakdown_status === "needs_review" ? "dashboard:nw_svt_review_required" : "dashboard:nw_svt_incomplete_hint")}</p>}<p className="mb-3 text-sm">{svt.mainline_reason}</p>{(["climaxes", "payoffs"] as const).map((kind) => <Section key={kind} title={t(`dashboard:nw_${kind}`)}>{svt[kind].length ? svt[kind].map((v, j) => <article key={j} className="mb-3 space-y-2 rounded border p-3"><p><strong>{t("dashboard:nw_moment_scene")}：</strong>{v.scene}</p><p className="text-xs text-muted-foreground">{v.reason}</p><div className="flex flex-wrap gap-2">{(v.note_ids ?? []).map((id) => <Button size="sm" variant="link" key={id} onClick={() => { setFocused(id); setTab("notes"); }}>{data.notes.find((n) => n.id === id)?.title ?? id}</Button>)}</div><strong>{t("dashboard:nw_moment_dialogue")}</strong>{(v.dialogues ?? []).map((d) => <blockquote key={d.id} className="border-l-2 border-primary/40 pl-3"><strong>{d.speaker}：</strong>{d.quote}<Evidence value={d.evidence} /></blockquote>)}</article>) : <p className="text-muted-foreground">{t("dashboard:nw_none")}</p>}</Section>)}<details className="mt-3 text-sm"><summary>{t("dashboard:nw_evidence")}</summary>{svt.evidence.map((e) => <Evidence key={`${e.source_file}:${e.start}:${e.end}`} value={e} />)}</details><Button size="sm" variant="outline" className="mt-3" onClick={() => { setSelected(svt.note_ids); setTab("notes"); }}>{t("dashboard:nw_select_sources")}</Button></article>)}{data.suggestions && data.suggestions.length > 0 && <Section title={t("dashboard:nw_ai_suggestions")}><ul className="list-disc pl-4">{data.suggestions.map((s) => <li key={s}>{s}</li>)}</ul><p className="mt-2 text-muted-foreground">{t("dashboard:nw_manual_only")}</p></Section>}</div>}
      {tab === "understanding" && <div className="relative min-h-0 flex-1 overflow-y-auto p-5 [scrollbar-gutter:stable]"><CrossChapterPanel conclusionsEnabled={data.settings?.conclusions_enabled !== false} decide={(value) => void act(async () => { if (NOVEL_WORKFLOW_SLOTS.some((slot) => isResourceBusy("text_novel_workflow", projectName, slot))) return; await API.decideNoteConclusion(projectName, {...value, source_basis:data.source_basis!}); await API.runNoteWorkflow(projectName, "conclusions", [value.note_id], data.source_basis!); })} value={data.understanding} notes={data.notes} busy={busy || working} organize={(report) => void act(() => API.organizeCrossQuestions(projectName, report.id, report.selected_note_ids, data.source_basis!))} select={(ids) => { setSelected(ids); setFocused(ids[0]); setTab("notes"); }} /></div>}
      {tab === "ledger" && <div className="relative min-h-0 flex-1 overflow-y-auto p-5 [scrollbar-gutter:stable]"><LedgerPanel ledger={data.ledger} notes={data.notes} select={(ids) => { setSelected(ids); setFocused(ids[0]); setTab("notes"); }} /></div>}
      {tab === "review" && <div className="relative min-h-0 flex-1 overflow-y-auto p-5 [scrollbar-gutter:stable]"><ReviewPanel reviews={data.reviews} notes={data.notes} select={(ids) => { setSelected(ids); setFocused(ids[0]); setTab("notes"); }} /></div>}
      {tab === "groups" && <NoteGroupsPanel groups={data.groups} notes={data.notes} disabled={busy || working || data.stale}
        select={(ids) => { setSelected(ids); setFocused(ids[0]); setTab("notes"); }}
        summarize={(group) => void act(() => API.runNoteWorkflow(projectName, "group_summary", group.note_ids, data.source_basis!, group.id))}
        usage={(group) => void act(() => API.setNoteGroupUsage(projectName, group.id, group.usage === "reference" ? "candidate" : "reference", data.source_basis!))}
        dissolve={(id) => void act(() => API.dissolveNoteGroup(projectName, id))} />}
      {tab === "scenes" && data.pending_assemblies?.map((pending) => <div key={pending.request_id} className="flex items-center gap-3 border-b bg-warn/10 p-3 text-sm"><span>{t("dashboard:nw_assembly_pending", { title: pending.title })}</span><Button disabled={busy || working} size="sm" onClick={() => void act(async () => { const created = await API.assembleDirectorEpisode(projectName, pending.shot_ids, pending.title, pending.source_basis, pending.request_id); if (await refreshAfterWrite(projectName, t) === "success") navigate(`/episodes/${created.episode}`); })}>{t("dashboard:nw_assembly_retry")}</Button></div>)}
      {tab === "scenes" && <SceneLibraryPanel
        projectName={projectName} assetOptions={assetOptions}
        saveExecution={async (shot, value) => {
          const edited = await API.editShotExecution(projectName, shot.id, data.source_basis!, shot.revision!, value);
          setShotSelection((ids) => ids.flatMap((id) => id === shot.id ? edited.shot_ids : [id]));
          await refreshAfterWrite(projectName, t); setRevision((n) => n + 1);
          setAssemblyRequest(crypto.randomUUID()); setTab("scenes", shot.id);
        }}
        draftExecution={(note, shot) => void act(() => API.productionAdvice(projectName, "shot_draft", [note], [shot], data.source_basis!))}
        assemblyActions={data.settings?.delivery_checks_enabled === false ? undefined : <DeliveryPanel key={projectName} projectName={projectName} sourceBasis={data.source_basis!} selection={shotSelection} title={episodeTitle} disabled={busy || working || data.stale} revision={revision + (working ? 1 : 0)} labels={sceneLibraryOrder(data.scene_batches ?? [], data.notes).shotLabels} load={(ids, title) => { setShotSelection(ids); setEpisodeTitle(title); setAssemblyRequest(crypto.randomUUID()); }} locate={(id) => setTab("scenes", id)} openAsset={openAsset} assemble={assembleSelection} />}
        completeProduction={(ids) => void act(() => API.runNoteWorkflow(projectName, "scenes", ids, data.source_basis!))}
        saveProduction={async (shot, basis, decisions) => {
          if (busy || working) throw new Error(t("dashboard:nw_working"));
          await API.saveShotProduction(projectName, shot, data.source_basis!, basis, decisions);
          await refreshAfterWrite(projectName, t);
          setRevision((n) => n + 1);
        }}
        openSvt={(id) => { setFocusedSvt(id); setTab("svt"); }}
        openAsset={(asset) => {
          const route = `/${{ character: "characters", scene: "scenes", prop: "props" }[asset.kind]}`;
          useAppStore.getState().triggerScrollTo({ type: asset.kind, id: asset.name, route });
          navigate(`/app/projects/${encodeURIComponent(projectName)}${route}`);
        }}
        batchSource={(basis, shotId, segment, utterance) => setSourceBatch({ basis, shotId, segment, utterance })}
        suggestSpeakers={(note, shot) => void act(() => API.suggestShotSpeakers(projectName, note, shot, data.source_basis!))}
        characters={Object.keys(project?.characters ?? {})}
        confirmQuestions={(batch, revision, reason, index, resolution) => void act(async () => { await API.confirmSceneQuestions(projectName, batch, revision, reason, data.source_basis!, index, resolution); await refreshAfterWrite(projectName, t); })}
        adoptRevision={(batch, revision) => void act(async () => { await API.adoptSceneRevision(projectName, batch, revision, data.source_basis!); await refreshAfterWrite(projectName, t); })}
        attribute={(shot, segment, utterance, speaker, revision, registerRole) => { setTab("scenes", shot); void act(async () => { await API.attributeNoteDialogue(projectName, shot, segment, utterance, speaker, data.source_basis!, revision, registerRole); await refreshAfterWrite(projectName, t); }); }}
        batches={data.scene_batches ?? []} notes={data.notes} disabled={busy || working || data.stale}
        selection={shotSelection} setSelection={(ids) => { setShotSelection(ids); setAssemblyRequest(crypto.randomUUID()); }}
        title={episodeTitle} setTitle={(value) => { setEpisodeTitle(value); setAssemblyRequest(crypto.randomUUID()); }}
        source={(id) => { setFocused(id); setTab("notes"); }}
        assemble={assembleSelection} />}

    </>}
    {sourceBatch && <SceneBatchSource key={`${sourceBatch.basis}:${sourceBatch.shotId}:${sourceBatch.segment}:${sourceBatch.utterance}`} projectName={projectName} {...sourceBatch} shotLabels={sceneLibraryOrder(data?.scene_batches ?? [], data?.notes ?? []).shotLabels} close={() => setSourceBatch(null)} />}
    <Dialog open={preview !== null} onOpenChange={(open) => { if (!open && !busy) setPreview(null); }}><DialogContent><DialogTitle>{t("dashboard:nw_preview")}</DialogTitle><DialogDescription>{t("dashboard:nw_preview_hint", { count: preview?.notes.length ?? 0 })}</DialogDescription><div className="relative max-h-80 overflow-y-auto text-sm">{preview?.notes.map((n) => <p key={n.id} className="py-1">{n.order}. {n.title} · {n.sections.length} {t("dashboard:nw_sections")}{n.needs_review && ` · ${t("dashboard:nw_review_heading")}`}</p>)}</div><DialogFooter><Button variant="outline" disabled={busy} onClick={() => setPreview(null)}>{t("common:cancel")}</Button><Button disabled={busy || working || !preview} onClick={() => void act(async () => { await API.initializeChapterNotes(projectName, preview!.source_basis); setPreview(null); setSelected([]); })}>{t("dashboard:nw_initialize")}</Button></DialogFooter></DialogContent></Dialog>
    <Dialog open={merging} onOpenChange={(open) => { if (!busy) setMerging(open); }}><DialogContent><DialogTitle>{t("dashboard:nw_merge")}</DialogTitle><DialogDescription>{t("dashboard:nw_manual_only")}</DialogDescription><Input aria-label={t("dashboard:nw_group_title")} placeholder={t("dashboard:nw_group_title")} value={title} onChange={(e) => setTitle(e.target.value)} /><ul className="relative max-h-64 list-disc overflow-y-auto pl-5 text-sm">{selectedNotes.map((n) => <li key={n.id}>{n.title}</li>)}</ul><DialogFooter><Button variant="outline" disabled={busy} onClick={() => setMerging(false)}>{t("common:cancel")}</Button><Button disabled={busy || !data?.source_basis} onClick={() => void act(async () => { await API.createNoteGroup(projectName, selected, title, data!.source_basis!); setMerging(false); setTab("groups"); })}>{t("dashboard:nw_confirm_merge")}</Button></DialogFooter></DialogContent></Dialog>

    {readingSettings && <ReadingSettings value={data?.settings ?? { summary_max_chars: 1200, understanding_enabled: true }} busy={busy || working} close={() => setReadingSettings(false)} save={(value) => void act(async () => { await API.updateNoteSettings(projectName, value); setReadingSettings(false); })}>
      {data?.initialized && <>
        <NoteReadingRange notes={data.notes} selected={selected} disabled={busy || working || data.stale || !data.source_basis} select={setSelected}>
          {(range, valid) => <ReadingScopePanel key={range.join(",")} scope={data.scope} notes={data.notes} selected={range} disabled={busy || working || data.stale || !data.source_basis || !valid} save={(extend) => void act(() => API.setNoteScope(projectName, range, data.source_basis!, extend))} />}
        </NoteReadingRange>
      </>}
    </ReadingSettings>}
    {upload && <SourceUploadDialog projectName={projectName} initialMode="whole_source" onClose={() => { setUpload(false); setRevision((n) => n + 1); }} />}
  </div>;
}
