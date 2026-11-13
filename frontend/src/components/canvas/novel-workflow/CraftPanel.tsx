import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogBody, DialogFooter } from "@/components/ui/dialog";
import { useConfirmLeave, useLeaveGuard } from "@/components/shared/edit-unit/LeaveGuard";
import type { CraftDecision, NoteEvidence, SceneLibraryBatch } from "@/types/novel-workflow";

export type SaveCraft = (batch: string, revision: string, value: CraftDecision) => Promise<void>;
const openingKeys = ["present", "positions", "props", "entering"] as const;
const emptyOpening = { present: "", positions: "", props: "", entering: "" };

function Editor({ initial, title, batch, labels, disabled, save, close }: { initial: CraftDecision; title: string; batch: SceneLibraryBatch; labels: Map<string, string>; disabled: boolean; save: SaveCraft; close: () => void }) {
  const { t } = useTranslation("dashboard");
  const [value, setValue] = useState(initial);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(JSON.stringify(initial));
  const leave = useConfirmLeave();
  async function submit() {
    if (disabled || saving || !batch.craft) return false;
    if (value.decision !== "restore" && value.reason.trim().length < 5) { setError(t("nw_craft_reason_required")); return false; }
    setSaving(true); setError("");
    try { await save(batch.basis, batch.craft.revision, value); setSaved(JSON.stringify(value)); return true; }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); return false; }
    finally { setSaving(false); }
  }
  useLeaveGuard({ dirty: JSON.stringify(value) !== saved, saving, save: submit, discard: close });
  const choices = value.kind === "coverage" ? ["confirm", "omit", "restore"] as const : ["accept", "dismiss"] as const;
  return <Dialog open onOpenChange={(open) => { if (!open && !saving) leave(close); }}><DialogContent size="lg">
    <DialogHeader><DialogTitle>{title}</DialogTitle></DialogHeader>
    <DialogBody><form id="craft-decision-form" className="space-y-4" onSubmit={(e) => { e.preventDefault(); void submit().then((ok) => { if (ok) close(); }); }}>
      {value.kind !== "opening" && <fieldset className="space-y-2"><legend className="font-semibold">{t("nw_craft_decision")}</legend>{choices.map((choice) => <label key={choice} className="flex items-center gap-2"><input type="radio" name="decision" checked={value.decision === choice} disabled={saving || disabled} onChange={() => setValue({ ...value, decision: choice })} />{t(`nw_craft_${choice}`)}</label>)}</fieldset>}
      {value.kind === "coverage" && value.decision === "confirm" && <fieldset className="space-y-2"><legend className="font-semibold">{t("nw_craft_shots")}</legend>{batch.scenes.flatMap((sc) => sc.shots).map((shot) => <label key={shot.id} className="flex gap-2 text-sm"><input type="checkbox" checked={value.shot_ids.includes(shot.id)} disabled={saving || disabled} onChange={(e) => setValue({ ...value, shot_ids: e.target.checked ? [...value.shot_ids, shot.id] : value.shot_ids.filter((id) => id !== shot.id) })} />{labels.get(shot.id) ?? shot.id} · {shot.title}</label>)}</fieldset>}
      {value.kind === "appearance" && value.decision === "accept" && <label className="block space-y-2"><span className="font-semibold">{t("nw_craft_constraint")}</span><Textarea required value={value.text} disabled={saving || disabled} onChange={(e) => setValue({ ...value, text: e.target.value })} /><span className="text-xs text-muted-foreground">{t("nw_craft_constraint_hint")}</span></label>}
      {value.kind === "opening" && openingKeys.map((key) => <label key={key} className="block space-y-2"><span className="font-semibold">{t(`nw_craft_${key}`)}</span><Textarea required={key === "present"} value={value.opening?.[key] ?? ""} disabled={saving || disabled} onChange={(e) => setValue({ ...value, opening: { ...(value.opening ?? emptyOpening), [key]: e.target.value } })} /></label>)}
      <label className="block space-y-2"><span className="font-semibold">{t("nw_craft_reason")}</span><Textarea required={value.decision !== "restore"} minLength={value.decision === "restore" ? undefined : 5} value={value.reason} disabled={saving || disabled} onChange={(e) => setValue({ ...value, reason: e.target.value })} /></label>
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </form></DialogBody>
    <DialogFooter><Button variant="outline" disabled={saving} onClick={() => leave(close)}>{t("common:cancel")}</Button><Button type="submit" form="craft-decision-form" disabled={saving || disabled}>{t(saving ? "nw_craft_saving" : "nw_craft_save")}</Button></DialogFooter>
  </DialogContent></Dialog>;
}

export function CraftPanel({ batch, disabled, labels, run, save, locate, source, openCharacter }: { batch: SceneLibraryBatch; disabled: boolean; labels: Map<string, string>; run?: (note: string, shot: string) => void; save?: SaveCraft; locate: (id: string) => void; source: (shot?: string, range?: NoteEvidence) => void; openCharacter?: (reference: string) => void }) {
  const { t } = useTranslation("dashboard");
  const [editor, setEditor] = useState<{ value: CraftDecision; title: string } | null>(null);
  const [notice, setNotice] = useState("");
  const craft = batch.craft;
  if (!craft) return batch.craft_error ? <p role="status" className="text-warn">{batch.craft_error}</p> : null;
  const first = batch.scenes[0]?.shots[0];
  const start = (kind: CraftDecision["kind"], item: string, title: string, extra: Partial<CraftDecision> = {}) => setEditor({ title, value: { kind, item_id: item, decision: kind === "coverage" ? "confirm" : kind === "opening" ? "save" : "accept", reason: "", shot_ids: [], text: "", ...extra } });
  const confirmed = craft.items.filter((i) => i.decision && !i.decision.stale).length;
  return <section className="space-y-3 rounded-xl border border-primary/25 bg-background p-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h3 className="font-bold">{t("nw_craft_title")}</h3>{run && first && <Button size="sm" disabled={disabled || !craft.reading_available} onClick={() => run(batch.note_id, first.id)}>{t(craft.review ? "nw_craft_recheck" : "nw_craft_check")}</Button>}</div>
    <p className="text-xs text-muted-foreground">{t("nw_craft_scope")}</p>
    {batch.stale && <p className="text-xs text-warn">{t("nw_craft_historical")}</p>}
    {craft.stale && <p role="status" className="text-sm text-warn">{t("nw_craft_stale")}</p>}
    {!craft.reading_available && <p role="status">{t("nw_craft_no_reading")}</p>}
    {notice && <p role="status" className="text-sm text-primary">{notice}</p>}
    <details className="rounded-lg border p-3"><summary className="cursor-pointer font-semibold">{t("nw_craft_actions")} · {confirmed}/{craft.items.length} {t("nw_craft_decided")}</summary>
      <div className="mt-3 space-y-3">{craft.items.map((item) => <article key={item.id} className="space-y-2 rounded border bg-muted/20 p-3 text-sm">
        <p className="font-semibold">{item.kind} · {item.title}</p><p className="leading-7">{item.text}</p>
        <p className="text-xs text-muted-foreground">{t(`nw_claim_${item.claim_type}`, { defaultValue: item.claim_type })}</p>
        {item.suggestion && <p className={item.suggestion.status === "covered" ? "text-muted-foreground" : "text-warn"}>{t("nw_craft_ai")} · {t(`nw_craft_${item.suggestion.status}`)}：{item.suggestion.reason}</p>}
        {item.decision && <p className="border-l-2 border-primary pl-2">{t(item.decision.stale ? "nw_craft_decision_stale" : "nw_craft_human")} · {t(item.decision.decision === "omit" ? "nw_craft_omit" : "nw_craft_confirm")}：{item.decision.reason}</p>}
        <div className="flex flex-wrap gap-2"><Button variant="outline" size="sm" onClick={() => source(undefined, item.evidence)}>{t("nw_craft_source")}</Button>{[...new Set([...(item.decision?.shot_ids ?? []), ...(item.suggestion?.shot_ids ?? [])])].map((id) => <Button key={id} variant="link" size="sm" onClick={() => locate(id)}>{labels.get(id) ?? id}</Button>)}{save && <Button size="sm" variant="outline" disabled={disabled} onClick={() => start("coverage", item.id, item.title, { shot_ids: item.decision?.shot_ids ?? item.suggestion?.shot_ids ?? [] })}>{t("nw_craft_handle")}</Button>}</div>
      </article>)}</div>
    </details>
    <details className="rounded-lg border p-3"><summary className="cursor-pointer font-semibold">{t("nw_craft_appearance")} · {craft.review?.appearance.length ?? 0}</summary>
      {!craft.review && <p className="mt-2 text-sm text-muted-foreground">{t("nw_craft_pending")}</p>}
      <div className="mt-3 space-y-3">{craft.review?.appearance.map((finding) => <article key={`${finding.shot_id}:${finding.reference}`} className="space-y-2 rounded border p-3 text-sm">
        <p className="font-semibold">{labels.get(finding.shot_id) ?? finding.shot_id} · {finding.reference} · {t(`nw_craft_${finding.status}`)}</p>
        <p>{finding.reason}</p>{finding.current_description && <div className="rounded border bg-muted/30 p-2"><strong>{t("nw_craft_current_design")}</strong><p className="mt-1 whitespace-pre-wrap">{finding.current_description}</p></div>}<blockquote className="border-l-2 pl-2">{finding.source_quote}</blockquote>{finding.suggestion && <p className="rounded bg-primary/10 p-2">{finding.suggestion}</p>}
        {finding.decision && <p>{t("nw_craft_human")}：{finding.decision.text || finding.decision.reason}</p>}
        <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => source(finding.shot_id, finding.source_evidence)}>{t("nw_craft_source")}</Button><Button size="sm" variant="outline" onClick={() => locate(finding.shot_id)}>{t("nw_craft_locate")}</Button>{openCharacter && <Button size="sm" variant="outline" onClick={() => openCharacter(finding.reference)}>{t("nw_craft_asset")}</Button>}{save && <Button size="sm" disabled={disabled || craft.stale} onClick={() => start("appearance", `${finding.shot_id}:${finding.reference}`, finding.reference, { text: finding.suggestion })}>{t("nw_craft_handle")}</Button>}</div>
      </article>)}</div>
    </details>
    <details className="rounded-lg border p-3"><summary className="cursor-pointer font-semibold">{t("nw_craft_opening")}</summary><div className="mt-3 space-y-3">{batch.scenes.map((scene) => {
      const suggestion = craft.review?.openings.find((s) => s.scene_id === scene.id);
      const state = scene.opening_state ?? suggestion?.state;
      return <article key={scene.id} className="space-y-2 rounded border p-3 text-sm"><p className="font-semibold">{scene.title} · {t(scene.opening_state ? "nw_craft_human" : "nw_craft_ai")}</p>{state ? <dl className="space-y-2">{openingKeys.map((key) => <div key={key}><dt className="font-semibold text-muted-foreground">{t(`nw_craft_${key}`)}</dt><dd className="whitespace-pre-wrap">{state[key] || t("nw_craft_unknown")}</dd></div>)}</dl> : <p>{t("nw_craft_pending")}</p>}{suggestion && <blockquote className="border-l-2 pl-2">{suggestion.source_quote}</blockquote>}{save && <Button size="sm" variant="outline" disabled={disabled} onClick={() => start("opening", scene.id, scene.title, { opening: state ?? emptyOpening, reason: scene.opening_state?.reason ?? "" })}>{t("nw_craft_opening_edit")}</Button>}</article>;
    })}</div></details>
    {editor && save && <Editor initial={editor.value} title={editor.title} batch={batch} labels={labels} disabled={disabled} save={async (...args) => { await save(...args); setNotice(t("nw_craft_saved")); }} close={() => setEditor(null)} />}
  </section>;
}
