import { ShotRhythmStrip } from "./ShotRhythmStrip";
import { type DecideDialogue } from "./DialogueCoveragePanel";
import { DialogueAttribution } from "./DialogueAttribution";
import { SceneQuestions, type ConfirmQuestion } from "./SceneQuestions";

import { ShotProductionPanel } from "./ShotProductionPanel";
import { sceneLibraryOrder } from "./scene-library-order";
import { ExecutionEditor } from "./ExecutionEditor";
import { ExecutionChecks } from "./ExecutionChecks";
import type { ReactNode } from "react";
import type { LibraryShot, ShotEdit, ExecutionAssetOption } from "@/types/novel-workflow";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChapterNote, SceneLibraryBatch, ShotDecisions, ShotAssetBinding } from "@/types/novel-workflow";

export function SceneLibraryPanel({ batches, notes, disabled, selection, setSelection, title, setTitle, assemble, source, characters = [], attribute, confirmQuestions, completeProduction, saveProduction, openAsset, openSvt, batchSource, suggestSpeakers, projectName, assetOptions = [], saveExecution, draftExecution, assemblyActions, help }: {
  help?: () => void;
  projectName?: string; assetOptions?: ExecutionAssetOption[];
  saveExecution?: (shot: LibraryShot, edit: ShotEdit) => Promise<void>;
  draftExecution?: (note: string, shot: string) => void;
  assemblyActions?: ReactNode;
  batchSource?: (basis: string, shotId?: string, segment?: number, utterance?: number, range?: import("@/types/novel-workflow").NoteEvidence) => void;
  suggestSpeakers?: (note: string, shot: string) => void;
  completeProduction?: (notes: string[]) => void;
  saveProduction?: (shot: string, revision: string, value: ShotDecisions) => Promise<void>;
  openAsset?: (asset: ShotAssetBinding) => void;
  openSvt?: (id: string, noteId?: string) => void;
  batches: SceneLibraryBatch[]; notes: ChapterNote[]; disabled: boolean;
  selection: string[]; setSelection: (ids: string[]) => void; title: string; setTitle: (title: string) => void;
  confirmQuestions?: ConfirmQuestion;
  decideDialogue?: DecideDialogue;
  characters?: string[]; attribute?: (shot: string, segment: number, utterance: number, speaker: string, revision: string, registerRole?: boolean) => void;
  assemble: () => void; source: (note: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const [rhythmSelection, setRhythmSelection] = useState(false);
  const [filter, setFilter] = useState("");
  const [editing, setEditing] = useState<{ shot: LibraryShot; batch: string; proposal: boolean } | null>(null);
  const { ordered, sceneLabels, shotLabels } = sceneLibraryOrder(batches.filter((b) => !b.stale), notes);
  const query = filter.trim().toLowerCase();
  const isNumberSearch = /^(SCN|SH)-\d+$/i.test(query);
  const allShots = ordered.flatMap((b) => b.scenes.flatMap((scene) => scene.shots.map((shot) => ({ ...shot, scene, stale: b.stale }))));
  const byId = new Map(allShots.map((shot) => [shot.id, shot]));
  const invalid = selection.some((id) => !byId.has(id) || byId.get(id)?.stale);
  const unresolved = selection.some((id) => byId.get(id)?.segments.some((s) => s.utterances.some((u) => u.kind === "dialogue" && !u.speaker?.trim())));
  const reviewBlocked = batches.some((b) => b.scenes.some((s) => s.shots.some((shot) => selection.includes(shot.id))) && ((b.review?.version === 2 ? b.review.issues?.some((i) => i.status === "open" && i.blocking && i.shot_ids.some((id) => selection.includes(id))) : !!b.review?.unresolved.length) || b.review?.revisions.some((r) => !r.applied && !r.superseded && selection.includes(b.scenes[r.scene_index]?.shots[r.shot_index]?.id))));
  const productionBlocked = batches.some((b) => b.scenes.some((s) => s.shots.some((sh) => selection.includes(sh.id) && (b.production_stale || sh.issues?.some((i) => i.blocking && i.code !== "speaker")))));
  const missingProduction = batches.filter((b) => !b.stale && (b.production_stale || b.scenes.some((sc) => sc.shots.some((sh) => !sh.production))));
  const total = selection.reduce((sum, id) => sum + (byId.get(id)?.segments.reduce((s, seg) => s + seg.duration_seconds, 0) ?? 0), 0);
  const toggle = (ids: string[]) => setSelection(ids.every((id) => selection.includes(id)) ? selection.filter((id) => !ids.includes(id)) : [...selection, ...ids.filter((id) => !selection.includes(id))]);
  const move = (index: number, offset: number) => { const next = [...selection]; [next[index], next[index + offset]] = [next[index + offset], next[index]]; setSelection(next); };
  return <div className="@container/scene-library relative min-h-0 flex-1 overflow-hidden"><div className="grid h-full min-h-0 grid-cols-1 grid-rows-[auto_minmax(0,1fr)] @min-[900px]/scene-library:grid-cols-[minmax(0,1fr)_20rem] @min-[900px]/scene-library:grid-rows-[minmax(0,1fr)]">
    <div className="relative min-h-0 min-w-0 space-y-4 overflow-y-auto bg-background p-4 [scrollbar-gutter:stable]">
      <p className="text-sm text-muted-foreground">{t("nw_scene_library_hint")}</p>
      {completeProduction && missingProduction.length > 0 && <Button disabled={disabled} onClick={() => completeProduction([...new Set(missingProduction.map((b) => b.note_id))])}>{t("nw_complete_production")}</Button>}
      <Input aria-label={t("nw_scene_search")} placeholder={t("nw_scene_search")} value={filter} onChange={(e) => setFilter(e.target.value)} />
      <div className="space-y-2"><label className="inline-flex items-center gap-2 text-sm"><input type="checkbox" checked={rhythmSelection} onChange={(e) => setRhythmSelection(e.target.checked)} />{t("nw_rhythm_selection")}</label><ShotRhythmStrip shots={rhythmSelection ? selection.flatMap((id) => byId.has(id) ? [byId.get(id)!] : []) : allShots.filter((shot) => !shot.stale)} labels={shotLabels} locate={(id) => { setFilter(shotLabels.get(id) ?? id); requestAnimationFrame(() => { const target = document.getElementById(`library-shot-${id}`); target?.scrollIntoView({ block: "center" }); target?.focus({ preventScroll: true }); }); }} />{rhythmSelection && !selection.length && <p className="text-sm text-muted-foreground">{t("nw_rhythm_empty")}</p>}</div>

      {!ordered.length && <p className="text-sm">{t("nw_scene_empty")}</p>}
      {ordered.map((batch, batchIndex) => <details key={batch.basis} open id={`scene-batch-${batch.basis}`} className="space-y-4 rounded-xl border border-primary/20 bg-card p-3 shadow-sm">
        <summary className="-mx-3 -mt-3 cursor-pointer rounded-t-xl border-b border-primary/15 bg-primary/5 px-4 py-3 text-base font-bold">{batch.scenes.map((sc) => `${sceneLabels.get(sc.id)} · ${sc.title}`).join(" / ")} · {batch.scenes.reduce((sum, scene) => sum + scene.shots.length, 0)} {t("nw_delivery_shots")}</summary>
        {(batchIndex === 0 || ordered[batchIndex - 1].note_id !== batch.note_id) && <button className="text-sm font-semibold text-primary underline" onClick={() => source(batch.note_id)}>{notes.find((n) => n.id === batch.note_id)?.title ?? batch.note_id}</button>}
        {batch.production_stale && <p className="text-sm text-warn">{t("nw_production_stale")}</p>}
        {batch.skipped_reason && <p className="text-sm text-muted-foreground">{t("nw_scene_skipped")}：{batch.skipped_reason}</p>}
        {batch.scenes.filter((scene) => isNumberSearch ? [sceneLabels.get(scene.id), ...scene.shots.map((shot) => shotLabels.get(shot.id))].some((label) => label?.toLowerCase() === query) : JSON.stringify(scene).toLowerCase().includes(query)).map((scene) => <article key={scene.id} aria-label={`${sceneLabels.get(scene.id)} · ${scene.title}`} className="overflow-hidden rounded-xl border border-border bg-muted/30 shadow-sm">
          <div className="space-y-3 border-b border-primary/20 bg-secondary p-4">
            <div className="flex items-center justify-between gap-3"><span className="rounded bg-primary px-2.5 py-1 font-mono text-sm font-bold text-primary-foreground">{sceneLabels.get(scene.id)}</span><span className="text-xs font-semibold text-muted-foreground">{t("nw_scene_shot_count", { count: scene.shots.length })}</span></div>
            <label className="flex items-center gap-3 text-lg font-bold"><input type="checkbox" aria-label={t("nw_select_scene", { title: scene.title })} disabled={disabled || batch.stale} checked={scene.shots.every((s) => selection.includes(s.id))} onChange={() => toggle(scene.shots.map((s) => s.id))} />{scene.title}</label>
            <p className="text-sm font-semibold text-muted-foreground">{scene.location} · {scene.time}</p><p className="border-t border-primary/15 pt-3 text-sm leading-7">{scene.purpose}</p>{scene.suggested_omission && <p className="text-xs text-muted-foreground">{t("nw_scene_omission_suggestion", {reason: scene.suggested_omission})}</p>}
          </div>
          {scene.shots.map((shot) => <div key={shot.id} id={`library-shot-${shot.id}`} tabIndex={-1} className="m-4 space-y-4 overflow-hidden rounded-xl border border-border bg-card p-4 shadow-xs">
            <header className="-mx-4 -mt-4 space-y-2 border-b bg-muted/50 px-4 py-3"><label className="flex items-center gap-3 text-base font-bold"><input type="checkbox" aria-label={t("nw_select_shot", { title: shot.title })} disabled={disabled || batch.stale} checked={selection.includes(shot.id)} onChange={() => toggle([shot.id])} />{shot.title}<span className="ml-auto text-xs">{t("nw_ui_reference_time", { seconds: shot.segments.reduce((n, s) => n + s.duration_seconds, 0) })}</span></label>
            <p className="font-mono text-xs font-semibold text-primary">{sceneLabels.get(scene.id)} · {shotLabels.get(shot.id)}</p></header>
            <section className="space-y-3 rounded-lg border border-primary/15 bg-background p-3"><h4 className="border-b border-primary/15 pb-2 text-sm font-bold">{t("nw_shot_performance")}</h4>
            {shot.segments.map((segment, i) => <div key={i} className="space-y-3 rounded-lg bg-muted/40 p-3 text-sm"><strong className="inline-block rounded border bg-card px-2 py-0.5 font-mono text-xs">{shot.segments.length > 1 ? `${shot.segments.reduce((sum, seg) => sum + seg.duration_seconds, 0) <= 15 ? t("nw_scene_phase") : "SEG"}${i + 1} · ` : ""}{segment.duration_seconds}s</strong><p className="leading-7">{segment.scene_description}</p>{segment.utterances.map((u, j) => <div key={j} className="rounded-r border-l-2 border-primary/30 bg-primary/5 p-3 text-foreground"><p className="leading-7"><span className="font-bold">{u.speaker ? `${u.speaker}：` : u.kind === "dialogue" ? `${t("nw_speaker_pending")}：` : ""}</span>{u.text}</p>{u.kind === "dialogue" && !u.speaker && <DialogueAttribution shot={shot} segment={i} utterance={j} characters={characters} disabled={disabled || batch.stale} attribute={attribute} source={batchSource ? () => batchSource(batch.basis, shot.id, i, j) : undefined} />}</div>)}</div>)}
            </section>
            <div className="flex flex-wrap gap-2">{batchSource && <Button size="sm" variant="outline" onClick={() => batchSource(batch.basis, shot.id)}>{t("nw_shot_source")}</Button>}{suggestSpeakers && shot.segments.some((seg) => seg.utterances.some((u) => u.kind === "dialogue" && !u.speaker)) && <Button size="sm" disabled={disabled || batch.stale} onClick={() => suggestSpeakers(batch.note_id, shot.id)}>{t("nw_speaker_ai")}</Button>}</div>
            <div className="flex flex-wrap gap-2">{saveExecution && <Button size="sm" disabled={disabled || batch.stale} onClick={() => setEditing({ shot, batch: batch.basis, proposal: false })}>{t("nw_exec_edit")}</Button>}{draftExecution && <Button size="sm" variant="outline" disabled={disabled || batch.stale} onClick={() => draftExecution(batch.note_id, shot.id)}>{t("nw_exec_ai_request")}</Button>}{shot.execution_draft && <Button size="sm" variant="outline" disabled={disabled || batch.stale || shot.execution_draft.stale} onClick={() => setEditing({ shot, batch: batch.basis, proposal: true })}>{t("nw_exec_ai_draft")}</Button>}{shot.execution_draft?.stale && <span className="text-xs text-warn">{t("nw_exec_draft_stale")}</span>}</div>
            {shot.execution_checks && shot.execution_checks.length > 0 && <details className="rounded-lg border bg-muted/15 p-3"><summary className="cursor-pointer text-sm font-semibold">{t("nw_ui_shot_checks", { hard: shot.execution_checks.filter((i) => i.hard).length, suggestions: shot.execution_checks.filter((i) => !i.hard).length })}</summary><p className="my-3 text-xs leading-6 text-muted-foreground">{t("nw_ui_shot_checks_hint")}</p><ExecutionChecks checks={shot.execution_checks} /></details>}
            <details className="rounded-lg border p-3"><summary className="cursor-pointer text-sm font-semibold">镜头设计与资产</summary><ShotProductionPanel shot={shot} context={batch.production_context} disabled={disabled || batch.stale || !!batch.production_stale} openAsset={openAsset} openSvt={openSvt ? (id) => openSvt(id, batch.note_id) : undefined} save={saveProduction && shot.revision ? (value) => saveProduction(shot.id, shot.revision!, value) : undefined} /></details>
            <details className="rounded-lg border border-dashed bg-muted/20 p-3 text-xs text-muted-foreground"><summary className="cursor-pointer font-semibold">{t("nw_evidence")}</summary><p className="mt-2">{t("nw_source_reference", { scene: scene.id, shot: shot.id })}</p><blockquote className="mt-2 border-l-2 pl-2">{shot.evidence.quote}</blockquote><button className="mt-2 underline" onClick={() => source(shot.evidence.note_id)}>{t("nw_group_view_notes")}</button></details>
          </div>)}
        </article>)}
        <details className="rounded-xl border border-border bg-muted/15 p-3"><summary className="cursor-pointer text-sm font-semibold">{t("nw_ui_scene_tools")}</summary><p className="mt-3 text-xs leading-6 text-muted-foreground">{t("nw_ui_scene_tools_hint")}</p><div className="mt-3 space-y-3">
        {batch.review && <details className="space-y-3 rounded-lg border border-warn/40 p-3"><summary className="cursor-pointer font-semibold">{t("nw_semantic_review")}{(batch.review.unresolved.length) > 0 && ` (${batch.review.unresolved.length})`}</summary><SceneQuestions key={batch.review_revision} batch={batch} disabled={disabled || batch.stale} confirm={confirmQuestions} source={(shotId) => batchSource ? batchSource(batch.basis, shotId ?? batch.scenes.flatMap((s) => s.shots).find((sh) => sh.segments.some((seg) => seg.utterances.some((u) => u.kind === "dialogue" && !u.speaker)))?.id) : source(batch.note_id)} shotLabels={shotLabels} locate={(id) => { setFilter(shotLabels.get(id) ?? id); requestAnimationFrame(() => document.getElementById(`library-shot-${id}`)?.scrollIntoView({ block: "center", behavior: "smooth" })); }} /></details>}
        </div></details>
      </details>)}
    </div>
    <aside className="order-first flex min-h-0 flex-col gap-3 border-b bg-card p-4 @min-[900px]/scene-library:order-last @min-[900px]/scene-library:border-b-0 @min-[900px]/scene-library:border-l" aria-label={t("nw_director_assembly")}>
      <div className="shrink-0 space-y-2"><h2 className="text-lg font-bold">{t("nw_director_assembly")}</h2><p className="text-base font-semibold text-primary">{t("nw_selected_shots", { count: selection.length, seconds: total })}</p><p className="text-xs leading-6 text-muted-foreground">{t("nw_assembly_next_hint")}</p></div>
      <div className="shrink-0 space-y-3">
      {help && <Button size="sm" variant="link" className="h-auto p-0" onClick={help}>{t("nw_ui_help")}</Button>}
      {!assemblyActions && productionBlocked && <p className="text-sm text-destructive">{t("nw_production_blocked")}</p>}
      {invalid && <p className="text-sm text-destructive">{t("nw_scene_stale")}</p>}
      {!assemblyActions && reviewBlocked && <p className="text-sm text-muted-foreground">{t("nw_ui_reference_review")}</p>}
      {!assemblyActions && unresolved && <p role="status" className="text-sm text-muted-foreground">{t("nw_ui_reference_speaker")}</p>}
      <label className="block space-y-1 text-sm"><span className="font-semibold">{t("nw_episode_title")}</span><Input aria-label={t("nw_episode_title")} placeholder={t("nw_episode_title")} value={title} disabled={disabled} maxLength={200} onChange={(e) => setTitle(e.target.value)} /></label>
      {!title.trim() && selection.length > 0 && <p className="text-xs text-muted-foreground">{t("nw_assembly_title_needed")}</p>}
      {assemblyActions ?? <Button className="w-full" disabled={disabled || invalid || productionBlocked || !selection.length || !title.trim()} onClick={assemble}>{t("nw_assemble_selected")}</Button>}
      <p className="text-xs text-muted-foreground">{t("nw_assembly_no_ai")}</p>
    </div>
      <ol aria-label={t("nw_director_order_hint")} className="relative min-h-0 max-h-32 flex-1 space-y-2 overflow-y-auto border-t pt-3 [scrollbar-gutter:stable] @min-[900px]/scene-library:max-h-none">{selection.map((id, i) => <li key={id} className="rounded border p-2 text-sm"><span>{i + 1}. {shotLabels.get(id)} · {byId.get(id)?.title ?? id}</span><div className="mt-1 flex gap-1"><Button variant="ghost" size="sm" disabled={disabled || i === 0} aria-label={t("nw_move_up", { index: i + 1 })} onClick={() => move(i, -1)}>↑</Button><Button variant="ghost" size="sm" disabled={disabled || i === selection.length - 1} aria-label={t("nw_move_down", { index: i + 1 })} onClick={() => move(i, 1)}>↓</Button><Button variant="ghost" size="sm" disabled={disabled} onClick={() => toggle([id])}>{t("nw_remove_selection")}</Button></div></li>)}</ol>
    </aside>
  </div>{editing && projectName && saveExecution && <ExecutionEditor key={`${editing.shot.id}:${editing.proposal}`} projectName={projectName} batch={editing.batch} shot={editing.shot} label={shotLabels.get(editing.shot.id) ?? editing.shot.id} assets={assetOptions} proposal={editing.proposal} disabled={disabled} close={() => setEditing(null)} save={async (value) => { await saveExecution(editing.shot, value); setEditing(null); }} />}</div>;
}
