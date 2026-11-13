import { ClaimBadge } from "./ClaimBadge";
import { useTranslation } from "react-i18next";
import type { ChapterNote, NoteRelation } from "@/types/novel-workflow";

function meaningful(value: string) {
  return !!value.trim() && !["未明确", "未知", "不明", "未提及", "未说明", "现在"].includes(value.trim());
}

const basicRelations = new Set(["父亲", "母亲", "父", "母", "儿子", "女儿", "子", "女", "老师", "学生", "同学", "同班同学", "师生", "兄弟", "姐妹", "哥哥", "姐姐", "弟弟", "妹妹"]);

export function storyRelations(relations: NoteRelation[]) {
  return relations.filter((r) => {
    if (r.record_kind === "changed" || r.record_kind === "established") return true;
    if (r.record_kind === "existing" && basicRelations.has(r.relation.trim())) return false;
    const hasChange = meaningful(r.previous) && r.previous !== r.relation;
    return !basicRelations.has(r.relation.trim()) || hasChange || meaningful(r.trigger);
  });
}

export function RelationDescription({ relation: r }: { relation: NoteRelation }) {
  const { t } = useTranslation("dashboard");
  const knownBefore = meaningful(r.previous);
  const changed = r.record_kind === "changed" && knownBefore && r.previous !== r.relation;
  const legacyChange = !r.record_kind || r.record_kind === "unclassified";
  return <>
    <strong>{t("nw_relation_identity", { subject: r.subject, target: r.target, relation: r.relation })}</strong>{r.claim_type && <ClaimBadge value={r} />}
    {changed || (legacyChange && knownBefore && r.previous !== r.relation) ? <p>{t("nw_relation_transition", { before: r.previous, after: r.relation })}</p>
      : <p className="text-xs text-muted-foreground">{t(r.record_kind === "established" ? "nw_relation_established" : (r.record_kind === "existing" || r.previous === r.relation) ? "nw_relation_existing" : "nw_relation_recorded")}</p>}
    {meaningful(r.story_time) && <p className="text-xs text-muted-foreground">{r.story_time}</p>}
    {meaningful(r.trigger) && <p>{r.trigger}</p>}
  </>;
}

export function ReadingQuestions({ reading }: { reading: NonNullable<ChapterNote["reading"]> }) {
  const { t } = useTranslation("dashboard");
  if (reading.conclusion_review) {
    const items = reading.conclusion_review.conclusions.filter((c) => c.status !== "resolved");
    return <section className="space-y-3 rounded-xl border p-5"><h3 className="font-bold">{t("nw_conclusions_title")}</h3><p className="text-xs text-muted-foreground">{t("nw_conclusions_resolved")} · {reading.conclusion_review.conclusions.length - items.length}</p>{items.map((item) => <article key={item.id} className="space-y-2 rounded-lg border p-3"><span className={`text-xs font-semibold ${item.blocking ? "text-destructive" : "text-muted-foreground"}`}>{t(`nw_conclusions_${item.status}`)}</span><p className="font-medium">{item.question}</p><p className="text-sm leading-6">{item.answer}</p></article>)}</section>;
  }
  const classified = new Map((reading.reading_questions ?? []).map((q) => [q.text, q.kind]));
  const questions = [...new Set([...reading.questions, ...(reading.overview?.questions ?? []), ...classified.keys()])];
  if (!questions.length) return null;
  return <section className="space-y-3 rounded-xl border border-warn/30 bg-warn/5 p-5">
    <h3 className="text-base font-bold">{t("nw_reading_questions")}</h3>
    <p className="text-xs leading-relaxed text-muted-foreground">{t("nw_reading_questions_hint")}</p>
    <ul className="space-y-3">{questions.map((q) => <li key={q} className="space-y-1 text-sm"><span className="rounded bg-muted px-2 py-1 text-xs text-muted-foreground">{t(`nw_question_kind_${classified.get(q) ?? "unclassified"}`)}</span><p>{q}</p></li>)}</ul>
  </section>;
}
