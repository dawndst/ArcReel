import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useTasksStore } from "@/stores/tasks-store";
import { API } from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogBody, DialogFooter } from "@/components/ui/dialog";
import { errMsg } from "@/utils/async";
import type { DeliveryPlan, DirectorDecision, SavedDelivery } from "@/types/novel-workflow";
import { useConfirmLeave, useLeaveGuard } from "@/components/shared/edit-unit/LeaveGuard";
import { ExecutionChecks } from "./ExecutionChecks";

export function DeliveryPanel({ projectName, sourceBasis, selection, title, disabled, revision, labels, load, locate, openAsset, assemble }: {
  projectName: string; sourceBasis: string; selection: string[]; title: string; disabled: boolean; revision: number;
  labels: Map<string, string>; load: (ids: string[], title: string) => void; locate: (id: string) => void;
  openAsset: (kind: "character" | "scene" | "prop", name: string) => void; assemble: () => void;
}) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [open, setOpen] = useState(false);
  const [plan, setPlan] = useState<DeliveryPlan | null>(null);
  const [saved, setSaved] = useState<SavedDelivery[]>([]);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [baseline, setBaseline] = useState("");
  const confirmLeave = useConfirmLeave();
  const [decision, setDecision] = useState<DirectorDecision>({ basis: "", reviewer: t("dashboard:nw_director_role"), story_intent: "", withheld: "", story_checked: false, timing_checked: false, continuity_checked: false, decisions: {} });
  useEffect(() => { let active = true; void API.deliveryPlans(projectName).then((v) => { if (active) setSaved(v); }).catch((e: unknown) => { if (active) setError(errMsg(e)); }); return () => { active = false; }; }, [projectName, revision]);
  async function refresh(ids = selection, name = title) {
    const current = await API.deliveryPreview(projectName, ids, name, sourceBasis, true);
    setPlan(current);
    const savedForm = localStorage.getItem(`arcreel:director:${projectName}:${current.basis}`);
    let localDraft: DirectorDecision | null = null;
    if (savedForm) { try { localDraft = JSON.parse(savedForm) as DirectorDecision; } catch { localStorage.removeItem(`arcreel:director:${projectName}:${current.basis}`); } }
    setDecision((d) => d.basis === current.basis ? d : localDraft?.basis === current.basis ? localDraft : current.decision ? { ...current.decision, basis: current.basis } : { ...d, basis: current.basis, story_intent: "", withheld: "", story_checked: false, timing_checked: false, continuity_checked: false, decisions: {} });
    if (decision.basis !== current.basis) setBaseline(current.decision ? JSON.stringify({ ...current.decision, basis: current.basis }) : "");
    return current;
  }
  async function run(action: () => Promise<void>) {
    if (disabled || acting) return;
    setActing(true); setError("");
    try { await action(); } catch (e) { setError(errMsg(e)); } finally { setActing(false); }
  }
  if (plan && (plan.shot_ids.join("|") !== selection.join("|") || plan.title !== title.trim())) { setPlan(null); setOpen(false); }
  const formKey = `arcreel:director:${projectName}:${plan?.basis ?? ""}`;
  useEffect(() => {
    if (open && plan && !plan.approved && decision.basis === plan.basis && (decision.story_intent || decision.withheld || Object.keys(decision.decisions).length)) localStorage.setItem(formKey, JSON.stringify(decision));
  }, [decision, formKey, open, plan]);
  function keepDraft() { localStorage.setItem(formKey, JSON.stringify(decision)); setBaseline(JSON.stringify(decision)); return Promise.resolve(true); }
  useLeaveGuard({ dirty: open && !plan?.approved && JSON.stringify(decision) !== baseline && !!(decision.story_intent || decision.withheld || Object.keys(decision.decisions).length), saving: acting, save: keepDraft });
  const hard = plan?.issues.filter((i) => i.hard) ?? [];
  const warnings = [...new Set([...(plan?.issues.filter((i) => !i.hard).map((i) => i.code) ?? []), ...(plan?.ai_review?.findings.map((f) => `story:${f.kind}`) ?? [])])];
  const busy = disabled || acting;
  async function download(final: boolean) {
    const blob = await API.exportDelivery(projectName, selection, title, sourceBasis, final);
    const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = final ? "production-package.zip" : "production-preparation.zip"; link.click(); URL.revokeObjectURL(url);
  }
  return <div className="space-y-3 border-t pt-3">
    <p className="text-xs leading-6 text-muted-foreground">{t("dashboard:nw_delivery_flow")}</p>
    <Button className="w-full" disabled={busy || !selection.length || !title.trim()} onClick={() => void run(async () => { await refresh(); setOpen(true); })}>{t("dashboard:nw_delivery_open")}</Button>
    {!!saved.length && <details className="rounded border p-2"><summary className="cursor-pointer text-sm font-semibold">{t("dashboard:nw_delivery_saved")}</summary><div className="mt-2 space-y-2">{saved.map((s) => <Button key={s.basis} variant="outline" size="sm" className="w-full justify-start" disabled={busy} onClick={() => { load(s.shot_ids, s.title); }}>{s.title} · {s.shot_ids.length} {t("dashboard:nw_delivery_shots")}</Button>)}</div></details>}
    {!open && error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    {open && plan && <Dialog open onOpenChange={(value) => { if (!acting) confirmLeave(() => setOpen(value)); }}><DialogContent size="xl"><DialogHeader><DialogTitle>{t("dashboard:nw_delivery_open")} · {plan.title}</DialogTitle><DialogDescription>{t("dashboard:nw_delivery_scope", { count: plan.shots.length, seconds: plan.seconds })}</DialogDescription></DialogHeader><DialogBody><div className="@container space-y-6">
      <nav className="sticky top-0 z-sticky flex flex-wrap gap-2 rounded border bg-popover p-2" aria-label={t("dashboard:nw_delivery_open")}>{([1, 2, 3] as const).map((step) => <Button key={step} size="sm" variant="outline" onClick={() => document.getElementById(`delivery-step-${step}`)?.scrollIntoView({ block: "start", behavior: "smooth" })}>{t(`dashboard:nw_delivery_step${step}`)}</Button>)}</nav>
      <section id="delivery-step-1" className="scroll-mt-16 space-y-3"><h3 className="text-lg font-bold">{t("dashboard:nw_delivery_step1")}</h3><ExecutionChecks checks={plan.issues} />{!!hard.length && <p className="font-semibold text-destructive">{t("dashboard:nw_delivery_hard", { count: hard.length })}</p>}<div className="flex flex-wrap gap-2">{[...new Set(plan.issues.map((i) => i.shot_id))].map((id) => <Button key={id} size="sm" variant="outline" disabled={acting} onClick={() => { confirmLeave(() => { setOpen(false); locate(id); }); }}>{t("dashboard:nw_delivery_edit_target", { shot: labels.get(id) ?? id })}</Button>)}</div>
      <details open className="rounded border p-3"><summary className="cursor-pointer font-semibold">{t("dashboard:nw_delivery_actual_script")}</summary><div className="mt-3 space-y-4">{plan.shots.map((shot, i) => <article key={shot.id} className="space-y-2 border-b pb-3"><strong>{i + 1}. {labels.get(shot.id) ?? shot.id} · {shot.title}</strong>{shot.scene && <p className="text-sm text-muted-foreground">{shot.scene.location} · {shot.scene.time} · {shot.scene.purpose}</p>}{shot.story_links && <details className="rounded border p-2 text-sm"><summary className="cursor-pointer font-semibold">{t("dashboard:nw_shot_moments")} · {shot.story_links.svt_id ?? t("dashboard:nw_shot_links_pending")}</summary>{shot.story_links.events.map((e) => <p key={e.id}>{e.title} · {e.action} · {e.outcome}</p>)}{shot.story_links.moments.map((m) => <div key={m.id}><strong>{m.scene}</strong>{m.dialogues.map((d) => <blockquote key={d.id}>{d.speaker}：{d.quote}</blockquote>)}</div>)}</details>}{shot.segments.map((seg, j) => <div key={j} className="space-y-1 rounded bg-muted/30 p-2 text-sm"><p className="font-semibold">SEG{j + 1} · {seg.duration_seconds}s</p><p>{seg.scene_description}</p>{seg.utterances.map((u, k) => <blockquote key={k} className="border-l-2 pl-2">{t(`dashboard:nw_delivery_${u.delivery ?? "unclassified"}`)} · {u.speaker ?? t("dashboard:nw_delivery_narration")}：{u.text}</blockquote>)}{seg.start_frame && <p className="text-xs text-muted-foreground">{t("dashboard:nw_exec_start_frame")}：{seg.start_frame}</p>}{seg.end_frame && <p className="text-xs text-muted-foreground">{t("dashboard:nw_exec_end_frame")}：{seg.end_frame}</p>}</div>)}</article>)}</div></details></section>
      <section id="delivery-step-2" className="scroll-mt-16 space-y-3"><h3 className="text-lg font-bold">{t("dashboard:nw_delivery_step2")}</h3><p className="text-sm text-muted-foreground">{t("dashboard:nw_delivery_human_hint")}</p><div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async () => { await API.productionAdvice(projectName, "selection_story", plan.note_ids, selection, sourceBasis, title); await useTasksStore.getState().refreshTasks(); setNotice(t("dashboard:nw_delivery_ai_queued")); })}>{t("dashboard:nw_delivery_ai")}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(async () => { await refresh(); })}>{t("dashboard:nw_delivery_refresh")}</Button></div>
      {plan.ai_review && <div className="space-y-3 rounded border border-primary/20 bg-primary/5 p-3"><p className="font-semibold">{plan.ai_review.summary}</p><p>{plan.ai_review.audience_understanding}</p>{plan.ai_review.findings.map((f, i) => <article key={i} className="space-y-1 rounded border bg-card p-3 text-sm"><strong>{f.shot_ids.map((id) => labels.get(id) ?? id).join("、")}</strong><p>{f.reason}</p><blockquote className="border-l-2 pl-2">{f.visible_evidence}</blockquote><p>{f.suggestion}</p></article>)}</div>}
      {plan.approved ? <p className="rounded border border-primary/30 bg-primary/10 p-3 font-semibold">{t("dashboard:nw_delivery_approved")} · {plan.decision?.reviewer}</p> : !hard.length && <div className="space-y-4 rounded border bg-muted/10 p-4"><label className="block space-y-1 text-sm"><strong>{t("dashboard:nw_delivery_reviewer")}</strong><Input value={decision.reviewer} disabled={busy} onChange={(e) => setDecision({ ...decision, reviewer: e.target.value })} /></label><label className="block space-y-1 text-sm"><strong>{t("dashboard:nw_delivery_intent")}</strong><Textarea value={decision.story_intent} disabled={busy} onChange={(e) => setDecision({ ...decision, story_intent: e.target.value })} /></label><label className="block space-y-1 text-sm"><strong>{t("dashboard:nw_delivery_withheld")}</strong><Textarea value={decision.withheld} disabled={busy} onChange={(e) => setDecision({ ...decision, withheld: e.target.value })} /></label>
      {warnings.map((code) => <label key={code} className="block space-y-1 text-sm"><strong>{code.startsWith("story:") ? t("dashboard:nw_delivery_story_decision", { kind: code.slice(6) }) : t(`dashboard:nw_exec_${code}`, { defaultValue: code })}</strong><Textarea placeholder={t("dashboard:nw_delivery_decision_hint")} value={decision.decisions[code] ?? ""} disabled={busy} onChange={(e) => setDecision({ ...decision, decisions: { ...decision.decisions, [code]: e.target.value } })} /></label>)}
      {(["story_checked", "timing_checked", "continuity_checked"] as const).map((field) => <label key={field} className="flex items-start gap-2 text-sm"><input type="checkbox" checked={decision[field]} disabled={busy} onChange={(e) => setDecision({ ...decision, [field]: e.target.checked })} />{t(`dashboard:nw_delivery_${field}`)}</label>)}<Button disabled={busy || decision.story_intent.trim().length < 10 || !decision.withheld.trim() || !decision.reviewer.trim() || !decision.story_checked || !decision.timing_checked || !decision.continuity_checked || warnings.some((code) => (decision.decisions[code]?.trim().length ?? 0) < 10)} onClick={() => void run(async () => { await API.confirmDelivery(projectName, selection, title, sourceBasis, { ...decision, basis: plan.basis }); await refresh(); setSaved(await API.deliveryPlans(projectName)); })}>{t("dashboard:nw_delivery_confirm")}</Button></div>}
      {!plan.episode && <Button disabled={busy || hard.some((i) => ["speaker_missing", "speaker_asset_missing", "asset_missing", "design_missing", "design_stale"].includes(i.code))} onClick={() => { setOpen(false); assemble(); }}>{t("dashboard:nw_delivery_assemble_reference")}</Button>}{plan.episode && <p className="font-semibold">{t("dashboard:nw_delivery_episode", { episode: plan.episode })}</p>}</section>
      <section id="delivery-step-3" className="scroll-mt-16 space-y-3"><h3 className="text-lg font-bold">{t("dashboard:nw_delivery_step3")}</h3><p className="text-sm text-muted-foreground">{t("dashboard:nw_delivery_material_hint")}</p>{plan.missing_materials?.map((m, i) => <p key={i} className="text-sm text-warn">{m.name} · {t(`dashboard:nw_delivery_missing_${m.code}`, { defaultValue: m.code })}</p>)}<div className="grid gap-3 @md:grid-cols-2">{plan.assets.map((a) => <article key={`${a.kind}:${a.name}`} className="space-y-2 rounded border bg-card p-3"><strong className="text-sm">{a.asset_code} · {a.name}</strong><p className="text-xs text-muted-foreground">{t(a.visible ? "dashboard:nw_visibility_visible" : "dashboard:nw_visibility_off_screen")}</p>{a.visible && a.image && <img src={API.getFileUrl(projectName, a.image, a.image_hash, { width: 640 })} alt={a.name} className="max-h-48 w-full rounded object-contain" />}{a.visible && !a.image && <p className="text-sm text-warn">{t("dashboard:nw_delivery_no_image")}</p>}{a.voice && <p className="text-sm">{t("dashboard:nw_delivery_voice")}：{a.voice_style || t("dashboard:nw_delivery_voice_missing")}</p>}<div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" disabled={acting} onClick={() => { confirmLeave(() => { setOpen(false); openAsset(a.kind, a.name); }); }}>{t("dashboard:nw_delivery_manage_asset")}</Button>{a.visible && <Button size="sm" disabled={busy || !plan.approved || !a.image_hash || a.image_approved} onClick={() => void run(async () => { await API.confirmDeliveryImage(projectName, selection, title, sourceBasis, plan.basis, a.asset_id, a.image_hash!, decision.reviewer); await refresh(); })}>{t(a.image_approved ? "dashboard:nw_delivery_image_approved" : "dashboard:nw_delivery_confirm_image")}</Button>}</div></article>)}</div><p className={`rounded border p-3 font-semibold ${plan.ready ? "border-primary/30 bg-primary/10" : "border-warn/40 bg-warn/10"}`}>{t(plan.ready ? "dashboard:nw_delivery_ready" : "dashboard:nw_delivery_not_ready")}</p></section>
      {notice && <p role="status" className="text-sm text-primary">{notice}</p>}
      {error && <p role="status" className="text-sm text-destructive">{error}</p>}
    </div></DialogBody><DialogFooter><Button variant="outline" disabled={acting} onClick={() => confirmLeave(() => setOpen(false))}>{t("common:close")}</Button><Button variant="outline" disabled={busy} onClick={() => void run(() => download(false))}>{t("dashboard:nw_delivery_download_draft")}</Button><Button disabled={busy || !plan.ready} onClick={() => void run(() => download(true))}>{t("dashboard:nw_delivery_download_final")}</Button></DialogFooter></DialogContent></Dialog>}
  </div>;
}
