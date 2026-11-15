import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { ChapterNote, ConclusionStatus, NoteConclusion, RelatedConclusionEvidence } from "@/types/novel-workflow";

export interface ConclusionDecisionInput { note_id: string; conclusion_id: string; status: ConclusionStatus; answer: string; reason: string; evidence_ids: string[] }
const statuses: ConclusionStatus[] = ["resolved", "partial", "unrevealed", "check", "conflict"];

function ConclusionCard({ item, noteId, busy, decide, recheck }: { recheck?: (noteId: string, conclusionId: string) => void; item: NoteConclusion; noteId: string; busy: boolean; decide?: (value: ConclusionDecisionInput) => void }) {
  const { t } = useTranslation("dashboard");
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState(item.status);
  const [answer, setAnswer] = useState(item.answer);
  const [reason, setReason] = useState("");
  const [evidenceIds, setEvidenceIds] = useState(item.evidence_ids);
  const [search, setSearch] = useState("");
  const evidence: RelatedConclusionEvidence[] = item.related_evidence ?? item.evidence.flatMap((value, index) => item.evidence_ids[index] ? [{ ...value, id: item.evidence_ids[index] }] : []);
  const advice = item.evidence_review;
  const labels = { supports: "直接支持", refutes: "直接反驳", context: "仅提供背景", insufficient: "不足以判断" };
  const matchingEvidence = evidence.filter((value) => value.quote.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <article className={`space-y-3 rounded-xl border p-4 ${item.blocking ? "border-destructive/50 bg-destructive/5" : item.status === "resolved" ? "border-primary/20 bg-primary/5" : "bg-card"}`}>
    <header className="space-y-2"><span className={`inline-block rounded px-2 py-1 text-xs font-semibold ${item.blocking ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground"}`}>{t(`nw_conclusions_${item.status}`)}</span><h3 className="font-semibold leading-6">{item.question}</h3></header>
    <p className="text-sm leading-6">{item.answer}</p>
    <p className="rounded bg-muted/60 p-3 text-xs leading-5"><strong>{t("nw_conclusions_constraint")}：</strong>{item.production_constraint}</p>
    <section className="space-y-3 rounded-lg border bg-muted/20 p-3"><h4 className="font-semibold">与本疑点相关的原文</h4>
      {!evidence.length && <p className="text-sm text-warn">尚未找到相关原文。不能据此判断结论真伪，也不需要从整章材料里自行找证据。</p>}
      {!!evidence.length && !advice && <p className="text-xs text-muted-foreground">以下为相关候选，尚不代表结论成立。可让 AI 逐条说明支持关系。</p>}
      {evidence.map((ev) => { const finding = advice?.findings.find((f) => f.evidence_id === ev.id); return <article key={ev.id} className="space-y-2 rounded border bg-background p-3"><p className="text-xs font-semibold">{ev.note_title ?? "原文章节"} · {finding ? labels[finding.relation] : "待核对候选"}</p><blockquote className="border-l-2 border-primary/40 pl-3 text-sm leading-7 whitespace-pre-wrap">{ev.quote}</blockquote><details className="text-xs text-muted-foreground"><summary className="cursor-pointer">引用位置</summary>{ev.source_file} · {ev.start}–{ev.end}</details>{"context_quote" in ev && !!ev.context_quote && <details className="text-xs"><summary className="cursor-pointer">查看这句的前后文</summary><blockquote className="mt-2 whitespace-pre-wrap border-l-2 pl-3">{ev.context_quote}</blockquote></details>}{finding ? <p className="text-sm leading-6"><strong>对应关系：</strong>{finding.explanation}</p> : ev.retrieval_reason && <p className="text-xs text-muted-foreground">{ev.retrieval_reason}</p>}</article>; })}
      {recheck && <Button size="sm" variant="outline" disabled={busy} onClick={() => recheck(noteId, item.id)}>AI 定向回查这条疑点</Button>}<p className="text-xs text-muted-foreground">仅核对当前疑点，最多6段候选、18000字符；使用当前及已读前章，不重跑整章。</p>
      {advice && <section className="space-y-2 rounded border border-primary/30 bg-primary/5 p-3"><h4 className="font-semibold">系统处理建议 · {t(`nw_conclusions_${advice.status}`)}</h4><p>{advice.answer}</p><p className="text-xs text-muted-foreground">{advice.reason}</p>{decide && <Button size="sm" disabled={busy} onClick={() => decide({ note_id:noteId, conclusion_id:item.id, status:advice.status, answer:advice.answer, reason:advice.reason, evidence_ids:advice.evidence_ids })}>采用建议并更新导览（调用AI）</Button>}<p className="text-xs text-muted-foreground">不会自动修改结论；可采用建议，也可在人工处理中修改。</p></section>}
    </section>
    {decide && <Button size="sm" variant="outline" disabled={busy} onClick={() => setEditing(!editing)}>{t("nw_conclusions_manual")}</Button>}
    {editing && <div className="space-y-3 border-t pt-3"><p className="text-xs leading-5 text-muted-foreground">{t("nw_conclusions_manual_hint")}</p><select className="w-full rounded border border-input bg-background p-2 text-sm" value={status} aria-label={t("nw_conclusions_title")} onChange={(event) => setStatus(event.target.value as ConclusionStatus)}>{statuses.map((s) => <option key={s} value={s}>{t(`nw_conclusions_${s}`)}</option>)}</select><Textarea aria-label={t("nw_conclusions_answer")} value={answer} onChange={(event) => setAnswer(event.target.value)} /><Textarea aria-label={t("nw_conclusions_reason")} placeholder={t("nw_conclusions_reason")} value={reason} onChange={(event) => setReason(event.target.value)} /><details className="space-y-2 rounded border p-3"><summary className="cursor-pointer text-sm font-semibold">{t("nw_conclusions_select_evidence", { count: evidenceIds.length })}</summary><Input aria-label={t("nw_conclusions_search_evidence")} placeholder={t("nw_conclusions_search_evidence")} value={search} onChange={(event) => setSearch(event.target.value)} /><div className="relative max-h-64 space-y-2 overflow-y-auto" role="region" aria-label={t("nw_source")}>{matchingEvidence.map((value) => <label key={value.id} className="flex items-start gap-2 rounded border p-2 text-xs leading-5"><input type="checkbox" className="mt-1" checked={evidenceIds.includes(value.id)} disabled={busy} onChange={(event) => setEvidenceIds((current) => event.target.checked ? [...current, value.id] : current.filter((id) => id !== value.id))} /><span>{value.quote}<span className="block text-muted-foreground">{value.source_file} · {value.start}–{value.end}</span></span></label>)}</div></details><Button size="sm" disabled={busy || !answer.trim() || !reason.trim() || (status === "resolved" && !evidenceIds.length)} onClick={() => decide?.({note_id:noteId, conclusion_id:item.id, status, answer, reason, evidence_ids:evidenceIds})}>{t("nw_conclusions_adopt")}</Button></div>}
  </article>;
}

export function ConclusionsPanel({ notes, busy, decide, initialNoteId, recheck }: { recheck?: (noteId: string, conclusionId: string) => void; initialNoteId?: string; notes: ChapterNote[]; busy: boolean; decide?: (value: ConclusionDecisionInput) => void }) {
  const { t } = useTranslation("dashboard");
  const available = notes.filter((n) => n.reading);
  const [active, setActive] = useState(initialNoteId ?? available.at(-1)?.id ?? "");
  const [filter, setFilter] = useState<"all" | ConclusionStatus>("all");
  const note = available.find((n) => n.id === active) ?? available.at(-1);
  const review = note?.reading?.conclusion_review;
  return <section className="@container space-y-4 rounded-xl border border-primary/30 bg-card p-5"><header className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-bold">{t("nw_conclusions_title")}</h2><select className="max-w-full rounded border border-input bg-background p-2 text-sm" aria-label={t("nw_conclusions_title")} value={note?.id ?? ""} onChange={(event) => setActive(event.target.value)}>{available.map((n) => <option key={n.id} value={n.id}>{n.order}. {n.title}</option>)}</select></header>
    {!review ? <p className="text-sm text-muted-foreground">{t("nw_conclusions_missing")}</p> : <><nav className="flex flex-wrap gap-2">{(["all", ...statuses] as const).map((s) => <Button key={s} size="sm" variant={filter === s ? "default" : "outline"} onClick={() => setFilter(s)}>{t(`nw_conclusions_${s}`)} ({review.conclusions.filter((c) => s === "all" || c.status === s).length})</Button>)}</nav><div className="grid gap-4 @xl:grid-cols-2">{review.conclusions.filter((c) => filter === "all" || c.status === filter).map((item) => <ConclusionCard key={`${note.id}:${review.basis}:${item.id}`} item={item} recheck={recheck} noteId={note.id} busy={busy} decide={decide} />)}</div></>}
  </section>;
}
