import { useState } from "react";
import { useTranslation } from "react-i18next";
import { BookOpen, Search } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { ChapterNote, UnderstandingLink, UnderstandingReport } from "@/types/novel-workflow";
import { ClaimBadge } from "./ClaimBadge";
import { FactEvidence } from "./UnderstandingPanels";

export function QuestionRegisterPanel({ report, notes, links, select, organize, busy }: {
  report: UnderstandingReport; notes: ChapterNote[]; links: UnderstandingLink[];
  select: (ids: string[]) => void; organize?: () => void; busy: boolean;
}) {
  const { t } = useTranslation("dashboard");
  const register = report.question_register;
  const [tab, setTab] = useState<string | null>(null);
  const title = (id: string) => notes.find((n) => n.id === id)?.title ?? id;
  const originals = new Map(register?.originals.map((q) => [q.id, q]));
  const evidence = new Map(links.map((link) => [link.id, link]));
  if (!report.unresolved.length) return <p className="text-muted-foreground">{t("nw_question_none")}</p>;
  return <div className="space-y-4">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h3 className="text-base font-bold">{t("nw_question_register")}</h3><p className="mt-1 text-xs text-muted-foreground">{register ? t("nw_question_reduced", { raw: register.original_count, count: register.group_count }) : t("nw_question_not_grouped", { count: report.unresolved.length })}</p></div>
      {organize && <Button variant="outline" size="sm" disabled={busy || report.stale} onClick={organize}>{t(register ? "nw_question_update" : "nw_question_organize")}</Button>}
    </header>
    {register?.stale && <p className="rounded-lg border border-warn/40 bg-warn/10 p-3 text-sm">{t("nw_question_stale")}</p>}
    {register && <>
      <p className="text-xs leading-relaxed text-muted-foreground">{t("nw_question_register_hint")}</p>
      <Tabs value={tab ?? (register.counts.extraction_check ? "extraction_check" : "plot_unrevealed")} onValueChange={(value) => setTab(value as string)}>
        <TabsList aria-label={t("nw_question_categories")}>
          <TabsTrigger value="extraction_check"><Search className="mr-1 size-4" />{t("nw_question_check")} ({register.counts.extraction_check})</TabsTrigger>
          <TabsTrigger value="plot_unrevealed"><BookOpen className="mr-1 size-4" />{t("nw_question_plot")} ({register.counts.plot_unrevealed})</TabsTrigger>
        </TabsList>
        {(["extraction_check", "plot_unrevealed"] as const).map((kind) => <TabsContent key={kind} value={kind}>
          <p className="py-3 text-sm text-muted-foreground">{t(kind === "extraction_check" ? "nw_question_check_hint" : "nw_question_plot_hint")}</p>
          <div className="grid grid-cols-[repeat(auto-fit,minmax(min(100%,22rem),1fr))] items-start gap-4">
            {register.groups.map((group, index) => group.kind !== kind ? null : <article key={group.id} className={`min-w-0 space-y-3 rounded-xl border border-l-4 bg-card p-4 ${kind === "extraction_check" ? "border-l-warn" : "border-l-primary"}`}>
              <header className="space-y-2"><span className="inline-flex rounded bg-muted px-2 py-1 font-mono text-xs">Q-{String(index + 1).padStart(3, "0")}</span><h4 className="font-bold leading-relaxed">{group.question}</h4></header>
              <p className="text-sm leading-relaxed">{group.explanation}</p>
              <p className="text-xs text-muted-foreground">{group.note_ids.map(title).join(" / ")}</p>
              <Button variant="outline" size="sm" onClick={() => select(group.note_ids)}>{t("nw_question_sources")}</Button>
              {!!group.link_ids.length && <details className="rounded-lg border bg-muted/15 p-3 text-sm"><summary className="cursor-pointer font-semibold">{t("nw_question_evidence", { count: group.link_ids.length })}</summary><p className="mt-2 text-xs text-muted-foreground">{t("nw_question_evidence_hint")}</p>{group.link_ids.map((id) => {
                const link = evidence.get(id);
                return link ? <section key={id} className="mt-3 space-y-2 border-t pt-3"><h5 className="font-semibold">{link.subject}</h5><p>{link.description}<ClaimBadge value={link} /></p>{link.evidence.map((e) => <div key={`${e.note_id}:${e.start}:${e.end}`}><p className="text-xs font-medium">{title(e.note_id)}</p><FactEvidence value={e} /></div>)}</section> : null;
              })}</details>}
              <details className="text-xs text-muted-foreground"><summary className="cursor-pointer">{t("nw_question_originals", { count: group.original_count })}</summary><ul className="mt-2 list-disc space-y-2 pl-4">{group.original_ids.map((id) => {
                const original = originals.get(id);
                return original ? <li key={id}><strong>{title(original.note_id)}：</strong>{original.question}</li> : null;
              })}</ul></details>
            </article>)}
          </div>
          {!register.counts[kind] && <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">{t("nw_question_category_empty")}</p>}
        </TabsContent>)}
      </Tabs>
    </>}
    {!register && <details className="rounded-lg border p-3 text-xs text-muted-foreground"><summary className="cursor-pointer">{t("nw_question_raw", { count: report.unresolved.length })}</summary><ul className="mt-2 list-disc space-y-2 pl-4">{report.unresolved.map((q, index) => <li key={index}>{title(q.note_id)}：{q.question}</li>)}</ul></details>}
  </div>;
}
