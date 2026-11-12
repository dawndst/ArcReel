import { useTranslation } from "react-i18next";
import type { ChapterNote, NoteRelation } from "@/types/novel-workflow";

function meaningful(value: string) {
  return !!value.trim() && !["未明确", "未知", "不明", "未提及", "未说明", "现在"].includes(value.trim());
}

export function RelationDescription({ relation: r }: { relation: NoteRelation }) {
  const { t } = useTranslation("dashboard");
  const knownBefore = meaningful(r.previous);
  const changed = r.record_kind === "changed" && knownBefore && r.previous !== r.relation;
  const legacyChange = !r.record_kind || r.record_kind === "unclassified";
  return <>
    <strong>{t("nw_relation_identity", { subject: r.subject, target: r.target, relation: r.relation })}</strong>
    {changed || (legacyChange && knownBefore && r.previous !== r.relation) ? <p>{t("nw_relation_transition", { before: r.previous, after: r.relation })}</p>
      : <p className="text-xs text-muted-foreground">{t(r.record_kind === "established" ? "nw_relation_established" : (r.record_kind === "existing" || r.previous === r.relation) ? "nw_relation_existing" : "nw_relation_recorded")}</p>}
    {meaningful(r.story_time) && <p className="text-xs text-muted-foreground">{r.story_time}</p>}
    {meaningful(r.trigger) && <p>{r.trigger}</p>}
  </>;
}

export function ReadingQuestions({ reading }: { reading: NonNullable<ChapterNote["reading"]> }) {
  const { t } = useTranslation("dashboard");
  const classified = new Map((reading.reading_questions ?? []).map((q) => [q.text, q.kind]));
  const questions = [...new Set([...reading.questions, ...(reading.overview?.questions ?? []), ...classified.keys()])];
  if (!questions.length) return null;
  return <section className="space-y-3 rounded-xl border p-4">
    <h3 className="font-semibold">{t("nw_reading_questions")}</h3>
    <p className="text-xs leading-relaxed text-muted-foreground">{t("nw_reading_questions_hint")}</p>
    <ul className="space-y-3">{questions.map((q) => <li key={q} className="space-y-1 text-sm"><span className="rounded bg-muted px-2 py-1 text-xs text-muted-foreground">{t(`nw_question_kind_${classified.get(q) ?? "unclassified"}`)}</span><p>{q}</p></li>)}</ul>
  </section>;
}
