import { RelationDescription, storyRelations } from "./ReadingAnnotations";
import { useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { ChapterNote, NovelLedger, NovelScopeReview, NoteEvidence } from "@/types/novel-workflow";

export function FactEvidence({ value }: { value: NoteEvidence }) {
  const { t } = useTranslation("dashboard");
  return <details className="mt-2 text-xs text-muted-foreground"><summary className="cursor-pointer">{t("nw_evidence")} · {value.source_file} · {value.start}–{value.end}</summary><blockquote className="mt-2 border-l-2 pl-3 whitespace-pre-wrap">{value.quote}</blockquote></details>;
}

export function ReadingEnrichment({ note }: { note: ChapterNote }) {
  const { t } = useTranslation("dashboard");
  const reading = note.reading;
  if (!reading) return null;
  const relations = storyRelations(reading.relations ?? []);
  return <div className="space-y-5 text-sm">
    {!!reading.highlights?.length && <section className="rounded-xl border bg-card p-5 shadow-xs"><h3 className="mb-4 border-b pb-3 text-base font-bold">{t("nw_highlights")}</h3>{reading.highlights.map((h) => <article key={h.id} className="mb-3 space-y-2 rounded-lg border border-border/60 bg-muted/20 p-4"><strong>{h.description}</strong><p className="mt-2 inline-flex rounded bg-primary/10 px-2 py-1 text-xs font-medium text-primary">{t(`nw_kind_${h.kind}` as "nw_kind_growth")} · {t(h.intensity === "large" ? "nw_large" : "nw_small")}</p><p>{h.beneficiary} · {h.reason}</p><p className="mt-2 border-l-2 pl-3">{h.visual}</p><FactEvidence value={h.evidence} /></article>)}</section>}
    {!!relations.length && <section className="rounded-xl border bg-card p-5 shadow-xs"><h3 className="mb-4 border-b pb-3 text-base font-bold">{t("nw_relations")}</h3>{relations.map((r) => <article key={r.id} className="mb-3 space-y-2 rounded-lg border border-border/60 bg-muted/20 p-4"><RelationDescription relation={r} /><FactEvidence value={r.evidence} /></article>)}</section>}
    {!!reading.threads?.length && <section className="rounded-xl border bg-card p-5 shadow-xs"><h3 className="mb-4 border-b pb-3 text-base font-bold">{t("nw_threads")}</h3>{reading.threads.map((r) => <article key={r.id} className="mb-3 space-y-2 rounded-lg border border-border/60 bg-muted/20 p-4"><strong>{t(r.kind === "seed" ? "nw_seed" : "nw_resolution")}：</strong>{r.description}<FactEvidence value={r.evidence} /></article>)}</section>}
  </div>;
}

export function LedgerPanel({ ledger, notes, select }: { ledger?: NovelLedger | null; notes: ChapterNote[]; select: (ids: string[]) => void }) {
  const { t } = useTranslation("dashboard");
  const [view, setView] = useState("characters");
  return <div className="min-w-0 space-y-5 text-sm"><p className="text-muted-foreground">{t("nw_ledger_hint")}</p>
    <Tabs value={view} onValueChange={(next) => setView(next as string)}>
      <div className="sticky top-0 z-sticky rounded-lg border bg-card p-1"><TabsList aria-label={t("nw_ledger_views")}><TabsTrigger value="characters">{t("nw_ledger_tab_characters")}</TabsTrigger><TabsTrigger value="threads">{t("nw_ledger_tab_threads")}</TabsTrigger></TabsList></div>
      <TabsContent value="characters"><div className="pt-3">
        {!ledger?.characters.length && <p className="rounded-lg border border-dashed p-5 text-muted-foreground">{t("nw_ledger_empty")}</p>}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,17rem),1fr))] items-start gap-4">{ledger?.characters.map((person) => {
          const relations = storyRelations(person.relations);
          const appearances = person.appear.map((id) => notes.find((n) => n.id === id)?.title ?? id).join(" / ");
          return <article key={person.id} className="flex min-w-0 flex-col gap-3 rounded-xl border bg-card p-4 shadow-xs">
            <header className="flex items-start gap-3 border-b pb-3"><span aria-hidden className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-lg font-bold text-primary">{person.name.slice(0, 1)}</span><div className="min-w-0"><h2 className="text-lg font-bold wrap-break-word">{person.name}</h2>{person.identity_scope && <p className="mt-1 text-xs text-muted-foreground">{person.identity_scope}</p>}</div></header>
            <p className="text-xs leading-6"><strong>{t("nw_aliases")}：</strong>{person.aliases.map((a) => a.alias).join(" / ") || t("nw_none")}</p>
            <p className="line-clamp-2 text-xs leading-6 text-muted-foreground" title={appearances}>{appearances}</p>
            <details className="rounded-lg border bg-muted/20 p-2"><summary className="cursor-pointer text-xs font-semibold">{t("nw_identity_evidence")}</summary>{[...person.mentions, ...person.aliases].map((record) => <FactEvidence key={record.id} value={record.evidence} />)}</details>
            {!!person.changes.length && <details className="rounded-lg border bg-muted/20 p-2"><summary className="cursor-pointer text-xs font-semibold">{t("nw_ledger_changes")} ({person.changes.length})</summary>{person.changes.map((change) => <div key={change.id} className="my-2 rounded bg-muted/40 p-2"><p>{change.before} → {change.after} · {change.story_time}</p><FactEvidence value={change.evidence} /></div>)}</details>}
            {!!relations.length && <details className="rounded-lg border bg-muted/20 p-2"><summary className="cursor-pointer text-xs font-semibold">{t("nw_relations")} ({relations.length})</summary>{relations.map((relation) => <div key={relation.id} className="my-2 border-l-2 pl-3"><RelationDescription relation={relation} /><FactEvidence value={relation.evidence} /></div>)}</details>}
            <Button size="sm" variant="outline" className="mt-auto w-full" onClick={() => select(person.appear)}>{t("nw_select_sources")}</Button>
          </article>;
        })}</div>
      </div></TabsContent>
      <TabsContent value="threads"><div className="space-y-5 pt-3">
        {!ledger?.threads.length && !ledger?.unmatched_resolutions.length && <p className="rounded-lg border border-dashed p-5 text-muted-foreground">{t("nw_ledger_threads_empty")}</p>}
        <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,20rem),1fr))] items-start gap-4">{ledger?.threads.map((seed) => <article key={seed.id} className="space-y-3 rounded-xl border bg-card p-4 shadow-xs"><span className={`inline-flex rounded px-2 py-1 text-xs font-semibold ${seed.resolutions?.length ? "bg-primary/10 text-primary" : "bg-warn/10 text-warn"}`}>{t(seed.resolutions?.length ? "nw_resolved" : "nw_pending")}</span><p className="font-semibold leading-7">{seed.description}</p><FactEvidence value={seed.evidence} />{seed.resolutions?.map((resolution) => <div key={resolution.id} className="mt-3 border-l-2 border-primary pl-3"><p>{resolution.description}</p><FactEvidence value={resolution.evidence} /></div>)}</article>)}</div>
        {!!ledger?.unmatched_resolutions.length && <section className="rounded-xl border bg-card p-5 shadow-xs"><h3 className="font-semibold">{t("nw_unmatched")}</h3>{ledger.unmatched_resolutions.map((resolution) => <div key={resolution.id} className="mt-3 rounded border bg-muted/20 p-3">{resolution.description}<FactEvidence value={resolution.evidence} /></div>)}</section>}
      </div></TabsContent>
    </Tabs>
  </div>;
}

export function ReviewPanel({ reviews, notes, select }: { reviews?: NovelScopeReview[]; notes: ChapterNote[]; select: (ids: string[]) => void }) {
  const { t } = useTranslation("dashboard");
  return <div className="space-y-5 text-sm"><p className="text-muted-foreground">{t("nw_review_hint")}</p>{!reviews?.length && <p>{t("nw_review_empty")}</p>}{reviews?.map((review) => <article key={review.id} className="space-y-4 rounded-xl border p-4"><h2 className="font-semibold">{t("nw_selected", { count: review.note_ids.length })} · {new Date(review.created_at).toLocaleString()}</h2><p className="text-xs text-muted-foreground">{review.note_ids.map((id) => notes.find((n) => n.id === id)?.title ?? id).join(" / ")}</p>{review.stale && <p className="text-destructive">{t("nw_review_stale")}</p>}{review.conclusion && <section className="space-y-2 rounded-lg border border-primary/30 bg-primary/5 p-4"><h3 className="font-semibold">{t("nw_range_overview")} · {review.conclusion.theme}</h3><p>{review.conclusion.mainline}</p><p><strong>{t("nw_preserve")}：</strong>{review.conclusion.must_preserve}</p><p><strong>{t("nw_adaptation_risks")}：</strong>{review.conclusion.adaptation_risks}</p><details><summary>{t("nw_evidence")}</summary>{review.conclusion.evidence_ids.map((id) => review.evidence[id] && <FactEvidence key={id} value={review.evidence[id].evidence} />)}</details></section>}{review.overview.map((section, i) => <section key={i} className="space-y-3"><h3 className="font-semibold">{section.theme}</h3><p className="leading-relaxed">{section.mainline}</p>{section.advice.map((a, j) => <article key={j} className="rounded-lg bg-muted/40 p-3"><strong className="text-primary">{t(`nw_advice_${a.action}`)}</strong><p className="mt-1 font-semibold">{a.note_ids.map((id) => notes.find((n) => n.id === id)?.title ?? id).join(" / ")}</p><p className="mt-2">{a.reason}</p><dl className="mt-2 space-y-1">{(["character_impact", "thread_impact", "dialogue_impact", "preserve"] as const).map((key) => <div key={key}><dt className="inline font-semibold">{t(`nw_${key}`)}：</dt><dd className="inline">{a[key]}</dd></div>)}</dl><details className="mt-2"><summary>{t("nw_evidence")}</summary>{a.evidence_ids.map((id) => review.evidence[id] && <FactEvidence key={id} value={review.evidence[id].evidence} />)}</details><Button variant="outline" size="sm" className="mt-3" disabled={review.stale} onClick={() => select(a.note_ids)}>{t("nw_select_sources")}</Button></article>)}{section.questions.map((q) => <p key={q}>{t("nw_questions")}：{q}</p>)}</section>)}<details><summary className="cursor-pointer">{t("nw_review_details")}</summary>{review.sections.map((s, i) => <div key={i} className="my-3"><strong>{s.theme}</strong><p>{s.mainline}</p>{s.advice.map((a, j) => <div key={j} className="my-2 border-l-2 pl-3"><strong>{t(`nw_advice_${a.action}`)}</strong> · {a.reason}<p>{a.preserve}</p></div>)}</div>)}</details></article>)}</div>;
}
