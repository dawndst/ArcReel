import { SceneQuestions, type ConfirmQuestion } from "./SceneQuestions";
import { MomentCoverage } from "./MomentCoverage";
import { ShotProductionPanel } from "./ShotProductionPanel";
import { sceneLibraryOrder } from "./scene-library-order";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ChapterNote, SceneLibraryBatch, ShotDecisions, ShotAssetBinding } from "@/types/novel-workflow";

export function SceneLibraryPanel({ batches, notes, disabled, selection, setSelection, title, setTitle, assemble, source, characters = [], attribute, adoptRevision, confirmQuestions, completeProduction, saveProduction, openAsset, openSvt }: {
  completeProduction?: (notes: string[]) => void;
  saveProduction?: (shot: string, revision: string, value: ShotDecisions) => Promise<void>;
  openAsset?: (asset: ShotAssetBinding) => void;
  openSvt?: (id: string) => void;
  batches: SceneLibraryBatch[]; notes: ChapterNote[]; disabled: boolean;
  selection: string[]; setSelection: (ids: string[]) => void; title: string; setTitle: (title: string) => void;
  confirmQuestions?: ConfirmQuestion;
  adoptRevision?: (batch: string, revision: string) => void;
  characters?: string[]; attribute?: (shot: string, segment: number, utterance: number, speaker: string, revision: string) => void;
  assemble: () => void; source: (note: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const [filter, setFilter] = useState("");
  const { ordered, sceneLabels, shotLabels } = sceneLibraryOrder(batches, notes);
  const query = filter.trim().toLowerCase();
  const isNumberSearch = /^(SCN|SH)-\d+$/i.test(query);
  const allShots = ordered.flatMap((b) => b.scenes.flatMap((scene) => scene.shots.map((shot) => ({ ...shot, scene, stale: b.stale }))));
  const byId = new Map(allShots.map((shot) => [shot.id, shot]));
  const invalid = selection.some((id) => !byId.has(id) || byId.get(id)?.stale);
  const unresolved = selection.some((id) => byId.get(id)?.segments.some((s) => s.utterances.some((u) => u.kind === "dialogue" && !u.speaker?.trim())));
  const reviewBlocked = batches.some((b) => b.scenes.some((s) => s.shots.some((shot) => selection.includes(shot.id))) && (!!b.review?.unresolved.length || b.review?.revisions.some((r) => !r.applied && selection.includes(b.scenes[r.scene_index]?.shots[r.shot_index]?.id))));
  const productionBlocked = batches.some((b) => b.scenes.some((s) => s.shots.some((sh) => selection.includes(sh.id) && (b.production_stale || sh.issues?.some((i) => i.blocking)))));
  const missingProduction = batches.filter((b) => !b.stale && (b.production_stale || b.scenes.some((sc) => sc.shots.some((sh) => !sh.production))));
  const total = selection.reduce((sum, id) => sum + (byId.get(id)?.segments.reduce((s, seg) => s + seg.duration_seconds, 0) ?? 0), 0);
  const toggle = (ids: string[]) => setSelection(ids.every((id) => selection.includes(id)) ? selection.filter((id) => !ids.includes(id)) : [...selection, ...ids.filter((id) => !selection.includes(id))]);
  const move = (index: number, offset: number) => { const next = [...selection]; [next[index], next[index + offset]] = [next[index + offset], next[index]]; setSelection(next); };
  return <div className="@container/scene-library relative min-h-0 flex-1 overflow-y-auto"><div className="grid grid-cols-1 @min-[900px]/scene-library:grid-cols-[minmax(0,1fr)_20rem]">
    <div className="min-w-0 space-y-4 p-5">
      <p className="text-sm text-muted-foreground">{t("nw_scene_library_hint")}</p>
      {completeProduction && missingProduction.length > 0 && <Button disabled={disabled} onClick={() => completeProduction([...new Set(missingProduction.map((b) => b.note_id))])}>{t("nw_complete_production")}</Button>}
      <Input aria-label={t("nw_scene_search")} placeholder={t("nw_scene_search")} value={filter} onChange={(e) => setFilter(e.target.value)} />
      <MomentCoverage batches={batches} selected={selection} locate={setFilter} />
      {!batches.length && <p className="text-sm">{t("nw_scene_empty")}</p>}
      {ordered.map((batch, batchIndex) => <div key={batch.basis} className="space-y-3">
        {(batchIndex === 0 || ordered[batchIndex - 1].note_id !== batch.note_id) && <button className="text-sm font-semibold text-primary underline" onClick={() => source(batch.note_id)}>{notes.find((n) => n.id === batch.note_id)?.title ?? batch.note_id}</button>}
        {batch.review && <details className="space-y-3 rounded-lg border border-warn/40 p-3"><summary className="cursor-pointer font-semibold">{t("nw_semantic_review")}{(batch.review.unresolved.length + batch.review.revisions.filter((r) => !r.applied).length) > 0 && ` (${batch.review.unresolved.length + batch.review.revisions.filter((r) => !r.applied).length})`}</summary><SceneQuestions key={batch.review_revision} batch={batch} disabled={disabled || batch.stale} confirm={confirmQuestions} source={() => source(batch.note_id)} shotLabels={shotLabels} locate={(id) => { setFilter(shotLabels.get(id) ?? id); requestAnimationFrame(() => document.getElementById(`library-shot-${id}`)?.scrollIntoView({ block: "center", behavior: "smooth" })); }} />{batch.review.revisions.map((r) => <article key={r.id} className="space-y-2 rounded border p-3 text-sm"><p>{r.reason}</p><p className="rounded bg-destructive/10 p-2"><del>{r.before}</del></p><p className="rounded bg-primary/10 p-2">{r.after}</p><details><summary>{t("nw_evidence")}</summary><blockquote>{r.source_quote}</blockquote></details>{r.applied ? <p className="text-primary">{t("nw_revision_applied")}</p> : <Button size="sm" disabled={disabled || batch.stale || !adoptRevision} onClick={() => adoptRevision?.(batch.basis, r.id)}>{t("nw_revision_adopt")}</Button>}</article>)}</details>}
        {batch.production_stale && <p className="text-sm text-warn">{t("nw_production_stale")}</p>}
        {batch.stale && <p className="text-sm text-destructive">{t("nw_scene_stale")}</p>}
        {batch.skipped_reason && <p className="text-sm text-muted-foreground">{t("nw_scene_skipped")}：{batch.skipped_reason}</p>}
        {batch.scenes.filter((scene) => isNumberSearch ? [sceneLabels.get(scene.id), ...scene.shots.map((shot) => shotLabels.get(shot.id))].some((label) => label?.toLowerCase() === query) : JSON.stringify(scene).toLowerCase().includes(query)).map((scene) => <article key={scene.id} className="rounded-xl border">
          <div className="space-y-1 border-b bg-muted/30 p-3">
            <label className="flex items-center gap-2 font-semibold"><input type="checkbox" aria-label={t("nw_select_scene", { title: scene.title })} disabled={disabled || batch.stale} checked={scene.shots.every((s) => selection.includes(s.id))} onChange={() => toggle(scene.shots.map((s) => s.id))} />{scene.title}</label>
            <p className="font-mono text-xs text-muted-foreground">{sceneLabels.get(scene.id)}</p><p className="text-xs">{scene.location} · {scene.time}</p><p className="text-sm">{scene.purpose}</p>
          </div>
          {scene.shots.map((shot) => <div key={shot.id} id={`library-shot-${shot.id}`} className="space-y-2 border-b p-3 last:border-b-0">
            <label className="flex items-center gap-2 text-sm font-semibold"><input type="checkbox" aria-label={t("nw_select_shot", { title: shot.title })} disabled={disabled || batch.stale} checked={selection.includes(shot.id)} onChange={() => toggle([shot.id])} />{shot.title}<span className="ml-auto text-xs">{shot.segments.reduce((n, s) => n + s.duration_seconds, 0)}s</span></label>
            <p className="font-mono text-xs text-muted-foreground">{sceneLabels.get(scene.id)} · {shotLabels.get(shot.id)}</p>
            <ShotProductionPanel shot={shot} context={batch.production_context} disabled={disabled || batch.stale || !!batch.production_stale} openAsset={openAsset} openSvt={openSvt} save={saveProduction && shot.revision ? (value) => saveProduction(shot.id, shot.revision!, value) : undefined} />
            <h4 className="text-sm font-semibold">{t("nw_shot_performance")}</h4>
            {shot.segments.map((segment, i) => <div key={i} className="space-y-1 rounded bg-muted/30 p-2 text-sm"><strong>{shot.segments.length > 1 ? `SEG${i + 1} · ` : ""}{segment.duration_seconds}s</strong><p>{segment.scene_description}</p>{segment.utterances.map((u, j) => <div key={j} className="text-primary"><p>{u.speaker ? `${u.speaker}：` : u.kind === "dialogue" ? `${t("nw_speaker_pending")}：` : ""}{u.text}</p>{u.kind === "dialogue" && !u.speaker && <div className="mt-2 rounded border border-warn/50 bg-warn/10 p-2 text-foreground"><p className="text-xs">{t("nw_speaker_hint")}</p>{attribute && <select className="mt-2 w-full rounded border bg-background p-2" aria-label={t("nw_speaker_confirm")} value="" disabled={disabled || batch.stale || !shot.revision} onChange={(e) => { if (e.target.value && shot.revision) attribute(shot.id, i, j, e.target.value, shot.revision); }}><option value="">{t("nw_speaker_confirm")}</option>{characters.map((name) => <option key={name} value={name}>{name}</option>)}</select>}</div>}</div>)}</div>)}
            <details className="text-xs text-muted-foreground"><summary>{t("nw_evidence")}</summary><p className="mt-2">{t("nw_source_reference", { scene: scene.id, shot: shot.id })}</p><blockquote className="mt-2 border-l-2 pl-2">{shot.evidence.quote}</blockquote><button className="mt-2 underline" onClick={() => source(shot.evidence.note_id)}>{t("nw_group_view_notes")}</button></details>
          </div>)}
        </article>)}
      </div>)}
    </div>
    <aside className="order-first space-y-3 border-l bg-card p-4 @min-[900px]/scene-library:sticky @min-[900px]/scene-library:top-0 @min-[900px]/scene-library:order-last @min-[900px]/scene-library:self-start" aria-label={t("nw_director_assembly")}>
      <h2 className="font-semibold">{t("nw_director_assembly")}</h2><p className="text-sm">{t("nw_selected_shots", { count: selection.length, seconds: total })}</p>
      <p className="text-xs text-muted-foreground">{t("nw_director_order_hint")}</p>
      <ol className="space-y-2">{selection.map((id, i) => <li key={id} className="rounded border p-2 text-sm"><span>{i + 1}. {shotLabels.get(id)} · {byId.get(id)?.title ?? id}</span><div className="mt-1 flex gap-1"><Button variant="ghost" size="sm" disabled={disabled || i === 0} aria-label={t("nw_move_up", { index: i + 1 })} onClick={() => move(i, -1)}>↑</Button><Button variant="ghost" size="sm" disabled={disabled || i === selection.length - 1} aria-label={t("nw_move_down", { index: i + 1 })} onClick={() => move(i, 1)}>↓</Button><Button variant="ghost" size="sm" disabled={disabled} onClick={() => toggle([id])}>{t("nw_remove_selection")}</Button></div></li>)}</ol>
      {productionBlocked && <p className="text-sm text-destructive">{t("nw_production_blocked")}</p>}
      {invalid && <p className="text-sm text-destructive">{t("nw_scene_stale")}</p>}
      {reviewBlocked && <p className="text-sm text-destructive">{t("nw_review_blocked")}</p>}
      {unresolved && <p role="status" className="text-sm text-destructive">{t("nw_speaker_blocked")}</p>}
      <Input aria-label={t("nw_episode_title")} placeholder={t("nw_episode_title")} value={title} disabled={disabled} maxLength={200} onChange={(e) => setTitle(e.target.value)} />
      <Button className="w-full" disabled={disabled || invalid || unresolved || reviewBlocked || productionBlocked || !selection.length || !title.trim()} onClick={assemble}>{t("nw_assemble_selected")}</Button>
      <p className="text-xs text-muted-foreground">{t("nw_assembly_no_ai")}</p>
    </aside>
  </div></div>;
}
