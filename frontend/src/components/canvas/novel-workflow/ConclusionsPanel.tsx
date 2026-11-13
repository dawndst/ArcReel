import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ChapterNote, ConclusionStatus, NoteConclusion, NoteEvidence } from "@/types/novel-workflow";
import { FactEvidence } from "./UnderstandingPanels";

export interface ConclusionDecisionInput { note_id: string; conclusion_id: string; status: ConclusionStatus; answer: string; reason: string; evidence_ids: string[] }
const statuses: ConclusionStatus[] = ["resolved", "partial", "unrevealed", "check", "conflict"];

function ConclusionCard({ item, noteId, busy, decide, availableEvidence }: { availableEvidence?: (NoteEvidence & { id: string })[]; item: NoteConclusion; noteId: string; busy: boolean; decide?: (value: ConclusionDecisionInput) => void }) {
  const { t } = useTranslation("dashboard");
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState(item.status);
  const [answer, setAnswer] = useState(item.answer);
  const [reason, setReason] = useState("");
  const [evidenceIds, setEvidenceIds] = useState(item.evidence_ids);
  const [search, setSearch] = useState("");
  const evidence = availableEvidence ?? item.evidence.flatMap((value, index) => item.evidence_ids[index] ? [{ ...value, id: item.evidence_ids[index] }] : []);
  const matchingEvidence = evidence.filter((value) => value.quote.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <article className={`space-y-3 rounded-xl border p-4 ${item.blocking ? "border-destructive/50 bg-destructive/5" : item.status === "resolved" ? "border-primary/20 bg-primary/5" : "bg-card"}`}>
    <header className="space-y-2"><span className={`inline-block rounded px-2 py-1 text-xs font-semibold ${item.blocking ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground"}`}>{t(`nw_conclusions_${item.status}`)}</span><h3 className="font-semibold leading-6">{item.question}</h3></header>
    <p className="text-sm leading-6">{item.answer}</p>
    <p className="rounded bg-muted/60 p-3 text-xs leading-5"><strong>{t("nw_conclusions_constraint")}：</strong>{item.production_constraint}</p>
    {!!item.evidence.length && <details className="text-xs"><summary className="cursor-pointer font-semibold">{t("nw_source")} ({item.evidence.length})</summary><div className="mt-3 space-y-3">{item.evidence.map((e, i) => <FactEvidence key={`${e.note_id}:${e.start}:${i}`} value={e} />)}</div></details>}
    {decide && <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(!editing)}>{t("nw_conclusions_manual")}</Button>}
    {editing && <div className="space-y-3 border-t pt-3"><p className="text-xs leading-5 text-muted-foreground">{t("nw_conclusions_manual_hint")}</p><select className="w-full rounded border border-input bg-background p-2 text-sm" value={status} aria-label={t("nw_conclusions_title")} onChange={(event) => setStatus(event.target.value as ConclusionStatus)}>{statuses.map((s) => <option key={s} value={s}>{t(`nw_conclusions_${s}`)}</option>)}</select><Textarea aria-label={t("nw_conclusions_answer")} value={answer} onChange={(event) => setAnswer(event.target.value)} /><Textarea aria-label={t("nw_conclusions_reason")} placeholder={t("nw_conclusions_reason")} value={reason} onChange={(event) => setReason(event.target.value)} /><details className="space-y-2 rounded border p-3"><summary className="cursor-pointer text-sm font-semibold">{t("nw_conclusions_select_evidence", { count: evidenceIds.length })}</summary><Input aria-label={t("nw_conclusions_search_evidence")} placeholder={t("nw_conclusions_search_evidence")} value={search} onChange={(event) => setSearch(event.target.value)} /><div className="relative max-h-64 space-y-2 overflow-y-auto" role="region" aria-label={t("nw_source")}>{matchingEvidence.map((value) => <label key={value.id} className="flex items-start gap-2 rounded border p-2 text-xs leading-5"><input type="checkbox" className="mt-1" checked={evidenceIds.includes(value.id)} disabled={busy} onChange={(event) => setEvidenceIds((current) => event.target.checked ? [...current, value.id] : current.filter((id) => id !== value.id))} /><span>{value.quote}<span className="block text-muted-foreground">{value.source_file} · {value.start}–{value.end}</span></span></label>)}</div></details><Button size="sm" disabled={busy || !answer.trim() || !reason.trim() || (status === "resolved" && !evidenceIds.length)} onClick={() => decide?.({note_id:noteId, conclusion_id:item.id, status, answer, reason, evidence_ids:evidenceIds})}>{t("nw_conclusions_adopt")}</Button></div>}
  </article>;
}

export function ConclusionsPanel({ notes, busy, decide }: { notes: ChapterNote[]; busy: boolean; decide?: (value: ConclusionDecisionInput) => void }) {
  const { t } = useTranslation("dashboard");
  const available = notes.filter((n) => n.reading);
  const [active, setActive] = useState(available.at(-1)?.id ?? "");
  const [filter, setFilter] = useState<"all" | ConclusionStatus>("all");
  const note = available.find((n) => n.id === active) ?? available.at(-1);
  const review = note?.reading?.conclusion_review;
  return <section className="@container space-y-4 rounded-xl border border-primary/30 bg-card p-5"><header className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-bold">{t("nw_conclusions_title")}</h2><select className="max-w-full rounded border border-input bg-background p-2 text-sm" aria-label={t("nw_conclusions_title")} value={note?.id ?? ""} onChange={(event) => setActive(event.target.value)}>{available.map((n) => <option key={n.id} value={n.id}>{n.order}. {n.title}</option>)}</select></header>
    {!review ? <p className="text-sm text-muted-foreground">{t("nw_conclusions_missing")}</p> : <><nav className="flex flex-wrap gap-2">{(["all", ...statuses] as const).map((s) => <Button key={s} size="sm" variant={filter === s ? "default" : "outline"} onClick={() => setFilter(s)}>{t(`nw_conclusions_${s}`)} ({review.conclusions.filter((c) => s === "all" || c.status === s).length})</Button>)}</nav><div className="grid gap-4 @xl:grid-cols-2">{review.conclusions.filter((c) => filter === "all" || c.status === filter).map((item) => <ConclusionCard key={`${note.id}:${review.basis}:${item.id}`} item={item} availableEvidence={review.available_evidence} noteId={note.id} busy={busy} decide={decide} />)}</div></>}
  </section>;
}
