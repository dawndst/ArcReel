import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogBody, DialogFooter } from "@/components/ui/dialog";
import { useConfirmLeave, useLeaveGuard } from "@/components/shared/edit-unit/LeaveGuard";
import type { LibraryShot, ShotDecisions, ShotAssetBinding, ShotProductionContext } from "@/types/novel-workflow";

const designKeys = ["purpose", "shot_size", "camera_angle", "camera_movement", "framing", "continuity", "sound"] as const;

function Editor({ shot, context, close, save, disabled }: { shot: LibraryShot; context: ShotProductionContext; close: () => void; save: (value: ShotDecisions) => Promise<void>; disabled: boolean }) {
  const { t } = useTranslation("dashboard");
  const initial = { shot_id: shot.id, event_ids: shot.production!.event_ids, moment_ids: shot.production!.moment_ids, design: shot.production!.design };
  const [draft, setDraft] = useState<ShotDecisions>(structuredClone(initial));
  const [saved, setSaved] = useState(JSON.stringify(initial));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const confirmLeave = useConfirmLeave();
  async function submit() {
    if (disabled || saving) return false;
    setSaving(true); setError("");
    try { await save(draft); setSaved(JSON.stringify(draft)); return true; }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); return false; }
    finally { setSaving(false); }
  }
  useLeaveGuard({ dirty: JSON.stringify(draft) !== saved, saving, save: submit, discard: close });
  const toggle = (field: "event_ids" | "moment_ids", id: string) => setDraft({ ...draft, [field]: draft[field].includes(id) ? draft[field].filter((v) => v !== id) : [...draft[field], id] });
  return <Dialog open onOpenChange={(open) => { if (!open && !saving) confirmLeave(close); }}><DialogContent>
    <DialogHeader><DialogTitle>{t("nw_design_edit")} · {shot.title}</DialogTitle></DialogHeader>
    <DialogBody><div className="space-y-4">
      {designKeys.map((key) => <label key={key} className="block space-y-1 text-sm"><span className="font-semibold">{t(`nw_design_${key}`)}</span><Textarea aria-label={t(`nw_design_${key}`)} value={draft.design[key]} disabled={saving || disabled} onChange={(e) => setDraft({ ...draft, design: { ...draft.design, [key]: e.target.value } })} /></label>)}
      <fieldset className="space-y-2"><legend className="font-semibold">{t("nw_events")}</legend>{context.events.map((e) => <label key={e.id} className="flex gap-2 text-sm"><input type="checkbox" disabled={saving || disabled} checked={draft.event_ids.includes(e.id)} onChange={() => toggle("event_ids", e.id)} />{e.title}</label>)}</fieldset>
      <fieldset className="space-y-2"><legend className="font-semibold">{t("nw_shot_moments")}</legend>{context.moments.map((m) => <label key={m.id} className="flex gap-2 text-sm"><input type="checkbox" disabled={saving || disabled} checked={draft.moment_ids.includes(m.id)} onChange={() => toggle("moment_ids", m.id)} />{m.scene}</label>)}</fieldset>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div></DialogBody><DialogFooter><Button variant="outline" disabled={saving} onClick={() => confirmLeave(close)}>{t("common:cancel")}</Button><Button disabled={saving || disabled || designKeys.some((k) => !draft.design[k].trim())} onClick={() => void submit().then((ok) => { if (ok) close(); })}>{t("common:save")}</Button></DialogFooter>
  </DialogContent></Dialog>;
}

export function ShotProductionPanel({ shot, context, disabled, save, openAsset, openSvt }: { shot: LibraryShot; context?: ShotProductionContext; disabled: boolean; save?: (value: ShotDecisions) => Promise<void>; openAsset?: (asset: ShotAssetBinding) => void; openSvt?: (id: string) => void }) {
  const { t } = useTranslation("dashboard");
  const [editing, setEditing] = useState(false);
  const production = shot.production;
  const moments = context?.moments.filter((m) => production?.moment_ids.includes(m.id)) ?? [];
  const bindings: ShotAssetBinding[] = production?.assets ?? ([['characters_in_scene', 'character'], ['scenes', 'scene'], ['props', 'prop']] as const).flatMap(([field, kind]) => [...new Set(shot.segments.flatMap((seg) => seg[field]))].map((name) => ({ kind, name, asset_id: null, asset_code: null, segments: [], missing: false })));
  return <section className="space-y-3 text-sm">
    {!shot.execution_checks && !!shot.issues?.length && <div className="space-y-1 rounded border border-warn/40 bg-warn/10 p-2">{shot.issues.map((issue, i) => <p key={i}>{t(`nw_shot_issue_${issue.code}`)}{issue.segment !== undefined && ` · SEG${issue.segment + 1}`}</p>)}</div>}
    <div className="space-y-3 rounded-lg border border-primary/15 bg-primary/5 p-3"><div className="flex flex-wrap items-center gap-2 border-b border-primary/10 pb-2"><strong className="text-sm font-bold">{t("nw_shot_moments")}</strong>{production?.svt_id && openSvt && <Button size="sm" variant="link" onClick={() => openSvt(production.svt_id)}>{t("nw_open_svt")}</Button>}</div>
      {!moments.length && <p className="text-muted-foreground">{t(production ? "nw_shot_no_moment" : "nw_shot_links_pending")}</p>}
      {moments.map((moment) => <details key={moment.id} className="rounded border p-2"><summary className="cursor-pointer font-medium">{t(moment.kind === "climaxes" ? "nw_moment_climax" : "nw_moment_payoff")} · {moment.scene}</summary><p className="mt-2">{moment.reason}</p>{moment.partial && <p className="mt-1 text-warn">{t("nw_moment_partial")}</p>}{moment.dialogues.map((d) => <blockquote key={d.id} className="mt-2 border-l-2 pl-2">{d.speaker}：{d.quote}</blockquote>)}</details>)}
    </div>
    <div className="space-y-3 rounded-lg border bg-muted/20 p-3"><h4 className="border-b pb-2 text-sm font-bold">{t("nw_shot_assets")}</h4><div className="flex flex-wrap gap-2">{bindings.map((a) => <Button key={`${a.kind}:${a.name}`} variant="outline" size="sm" disabled={a.missing || !openAsset} onClick={() => openAsset?.(a)}>{a.asset_code ?? t(`nw_${a.kind}`)} · {a.name}{a.variant && ` / ${a.variant}`}{a.state && ` · ${a.state}`}</Button>)}</div>{!bindings.length && <p className="text-muted-foreground">{t("nw_shot_no_assets")}</p>}</div>
    {production && <details className="rounded-lg border bg-background p-3"><summary className="cursor-pointer font-semibold">{t("nw_shot_design")}<span className="ml-2 text-xs font-normal text-muted-foreground">{production.design.shot_size} · {production.design.camera_angle} · {production.design.camera_movement}</span></summary><dl className="mt-2 space-y-2">{designKeys.map((key) => <div key={key}><dt className="mb-1 text-xs font-bold text-muted-foreground">{t(`nw_design_${key}`)}</dt><dd className="leading-7 whitespace-pre-wrap">{production.design[key]}</dd></div>)}</dl>{save && context && <Button size="sm" variant="outline" className="mt-3" disabled={disabled} onClick={() => setEditing(true)}>{t("nw_design_edit")}</Button>}</details>}
    {editing && save && context && <Editor shot={shot} context={context} disabled={disabled} close={() => setEditing(false)} save={save} />}
  </section>;
}
