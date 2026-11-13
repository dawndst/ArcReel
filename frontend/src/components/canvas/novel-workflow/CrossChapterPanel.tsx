import { ConclusionsPanel, type ConclusionDecisionInput } from "./ConclusionsPanel";
import { ClaimBadge } from "./ClaimBadge";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ChapterNote, NovelWorkflow, UnderstandingReport } from "@/types/novel-workflow";
import { QuestionRegisterPanel } from "./QuestionRegisterPanel";
import { FactEvidence } from "./UnderstandingPanels";

export function ReadingSettings({ value, busy, close, save, children }: { children?: ReactNode; value: NonNullable<NovelWorkflow["settings"]>; busy: boolean; close: () => void; save: (value: NonNullable<NovelWorkflow["settings"]>) => void }) {
  const { t } = useTranslation(["dashboard", "common"]);
  const [limit, setLimit] = useState(String(value.summary_max_chars));
  const [enabled, setEnabled] = useState(value.understanding_enabled);
  const [craft, setCraft] = useState(value.craft_checks_enabled !== false);
  const [delivery, setDelivery] = useState(value.delivery_checks_enabled !== false);
  const [conclusions, setConclusions] = useState(value.conclusions_enabled !== false);
  const [calls, setCalls] = useState(String(value.max_model_calls ?? 100));
  const parsedCalls = Number(calls);
  const parsed = Number(limit);
  return <Dialog open onOpenChange={(open) => { if (!open && !busy) close(); }}><DialogContent size="lg"><DialogHeader><DialogTitle>{t("dashboard:nw_read_settings")}</DialogTitle><DialogDescription>{t("dashboard:nw_settings_hint")}</DialogDescription></DialogHeader><DialogBody>{children}<label htmlFor="note-summary-limit" className="space-y-2 text-sm"><span className="font-semibold">{t("dashboard:nw_summary_limit")}</span><Input id="note-summary-limit" type="number" min={400} max={3000} step={100} value={limit} onChange={(event) => setLimit(event.target.value)} aria-label={t("dashboard:nw_summary_limit")} /></label><label aria-label={t("dashboard:nw_understanding_switch")} htmlFor="note-understanding-enabled" className="flex items-start gap-3 text-sm"><input id="note-understanding-enabled" type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} className="mt-1" /><span><strong>{t("dashboard:nw_understanding_switch")}</strong><span className="mt-1 block text-muted-foreground">{t("dashboard:nw_understanding_switch_hint")}</span></span></label><label className="flex items-start gap-3 text-sm"><input type="checkbox" checked={delivery} onChange={(e) => setDelivery(e.target.checked)} /><span>{t("dashboard:nw_delivery_switch")}<span className="mt-1 block text-muted-foreground">{t("dashboard:nw_delivery_switch_hint")}</span></span></label><label className="flex items-start gap-3 text-sm"><input type="checkbox" checked={craft} onChange={(e) => setCraft(e.target.checked)} /><span>{t("dashboard:nw_craft_switch")}<span className="mt-1 block text-muted-foreground">{t("dashboard:nw_craft_switch_hint")}</span></span></label><label htmlFor="note-conclusions-enabled" aria-label={t("dashboard:nw_conclusions_switch")} className="flex items-start gap-3 text-sm"><input id="note-conclusions-enabled" type="checkbox" checked={conclusions} onChange={(event) => setConclusions(event.target.checked)} /><span><strong>{t("dashboard:nw_conclusions_switch")}</strong><span className="mt-1 block text-muted-foreground">{t("dashboard:nw_conclusions_hint")}</span></span></label><label className="space-y-2 text-sm"><span className="font-semibold">{t("dashboard:nw_calls_limit")}</span><Input type="number" min={1} max={500} value={calls} onChange={(event) => setCalls(event.target.value)} aria-label={t("dashboard:nw_calls_limit")} /><span className="block text-xs leading-6 text-muted-foreground">{t("dashboard:nw_calls_hint")}</span></label><p className="text-xs text-muted-foreground">{t("dashboard:nw_conclusions_size_limit")}</p></DialogBody><DialogFooter><Button variant="outline" disabled={busy} onClick={close}>{t("common:cancel")}</Button><Button disabled={busy || !Number.isInteger(parsed) || parsed < 400 || parsed > 3000 || !Number.isInteger(parsedCalls) || parsedCalls < 1 || parsedCalls > 500} onClick={() => save({ summary_max_chars: parsed, understanding_enabled: enabled, delivery_checks_enabled: delivery, craft_checks_enabled: craft, conclusions_enabled: conclusions, max_model_calls: parsedCalls })}>{t("common:save")}</Button></DialogFooter></DialogContent></Dialog>;
}

export function CrossChapterPanel({ value, notes, select, organize, decide, conclusionsEnabled = true, busy = false }: {
  value: NovelWorkflow["understanding"]; notes: ChapterNote[]; select: (ids: string[]) => void;
  organize?: (report: UnderstandingReport) => void; decide?: (value: ConclusionDecisionInput) => void; busy?: boolean; conclusionsEnabled?: boolean;
}) {
  const { t } = useTranslation("dashboard");
  const title = (id: string) => notes.find((n) => n.id === id)?.title ?? id;
  const renderReport = (report: UnderstandingReport) => <section className="space-y-4 rounded-xl border bg-card p-4">
    <header className="border-b pb-3"><h2 className="font-semibold">{t("nw_reread_report")} · {new Date(report.created_at).toLocaleString()}</h2>
      {report.stale && <p className="text-destructive">{t("nw_review_stale")}</p>}
      <p className="mt-2 text-xs text-muted-foreground">{t("nw_search_coverage", { searched: report.searched_note_count, inspected: report.inspected_note_ids.length })} · {report.inspected_note_ids.map(title).join(" / ")}</p>
      {report.unread_inspected_note_ids.length > 0 && <p className="text-xs text-muted-foreground">{t("nw_partial_reread")}</p>}
    </header>
    <QuestionRegisterPanel report={report} notes={notes} links={report.links ?? value?.links ?? []} select={select} busy={busy} organize={organize ? () => organize(report) : undefined} />
    <details className="border-t pt-3 text-xs text-muted-foreground"><summary className="cursor-pointer">{t("nw_retrieval_trace")}</summary>{report.inspections.map((step, i) => <p key={i} className="mt-2">{step.round} · {step.queries.join(" / ")} → {step.note_ids.map(title).join(" / ")}</p>)}</details>
  </section>;
  return <div className="space-y-5 text-sm">
    {conclusionsEnabled && <ConclusionsPanel notes={notes} busy={busy} decide={decide} />}
    <p className="rounded-lg border border-primary/30 bg-primary/5 p-4">{t("nw_understanding_hint")}</p>
    {!value?.reports.length && <p className="text-muted-foreground">{t("nw_understanding_empty")}</p>}
    <details className="rounded-xl border p-4"><summary className="cursor-pointer font-semibold">{t("nw_conclusions_raw")}</summary>
    {value?.reports.map((report, index) => index === 0 ? <div key={report.id}>{renderReport(report)}</div> : <details key={report.id} className="rounded-xl border p-4"><summary className="cursor-pointer font-semibold">{t("nw_reread_report")} · {new Date(report.created_at).toLocaleString()}</summary><div className="mt-4">{renderReport(report)}</div></details>)}
    {!!value?.links.length && <details className="rounded-xl border p-4"><summary className="cursor-pointer font-semibold">{t("nw_question_links", { count: value.links.length })}</summary><div className="mt-4 space-y-4">{value.links.map((link) => <article key={link.id} className="space-y-3 rounded-xl border p-4"><div className="flex flex-wrap items-center gap-2"><h2 className="font-semibold">{link.subject}</h2><span className="rounded bg-muted px-2 py-1 text-xs">{t(`nw_link_${link.kind}`)}</span><span className="text-xs text-primary">{t(link.status === "supported" ? "nw_link_supported" : "nw_questions")}</span></div><p className="leading-relaxed">{link.description}<ClaimBadge value={link} /></p><dl className="space-y-2"><div><dt className="inline font-semibold">{t("nw_story_time")}：</dt><dd className="inline">{link.story_time}</dd></div><div><dt className="inline font-semibold">{t("nw_revealed_at")}：</dt><dd className="inline">{title(link.revealed_at.note_id)} · {link.revealed_at.offset}</dd></div></dl><p className="text-xs text-muted-foreground">{link.note_ids.map(title).join(" / ")}</p>{link.evidence.map((e) => <div key={`${e.note_id}:${e.start}`}><strong className="text-xs">{title(e.note_id)}</strong><FactEvidence value={e} /></div>)}<Button variant="outline" size="sm" onClick={() => select(link.note_ids)}>{t("nw_select_sources")}</Button></article>)}</div></details>}
    </details>
  </div>;
}
