import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { SceneLibraryBatch } from "@/types/novel-workflow";

export type ConfirmQuestion = (batch: string, revision: string, reason: string, index: number, resolution: "repaired" | "false_positive") => void;

export function SceneQuestions({ batch, disabled, confirm, locate, source, shotLabels }: {
  batch: SceneLibraryBatch; disabled: boolean; confirm?: ConfirmQuestion;
  locate: (id: string) => void; source: () => void; shotLabels: Map<string, string>;
}) {
  const { t } = useTranslation("dashboard");
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [modes, setModes] = useState<Record<number, "repaired" | "false_positive">>({});
  const review = batch.review;
  if (!review) return null;
  const missing = batch.scenes.flatMap((s) => s.shots).filter((shot) => shot.segments.some((seg) => seg.utterances.some((u) => u.kind === "dialogue" && !u.speaker?.trim())));
  const repairBlocked = missing.length > 0 || review.revisions.some((r) => !r.applied);
  return <div className="space-y-3">
    {review.unresolved.map((question, index) => <article key={index} className="space-y-3 rounded border border-warn/40 p-3">
      <p className="text-sm font-medium">{index + 1}. {question.replace(/utterances/gi, t("nw_question_dialogue"))}</p>
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={source}>{t("nw_batch_source")}</Button>{missing.map((shot) => <Button key={shot.id} size="sm" variant="outline" onClick={() => locate(shot.id)}>{t("nw_question_locate", { shot: shotLabels.get(shot.id) ?? shot.id })}</Button>)}</div>
      <p className="text-xs text-muted-foreground">{t("nw_question_hint")}</p>
      {confirm && <>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant={modes[index] === "repaired" ? "default" : "outline"} disabled={disabled || repairBlocked} onClick={() => setModes({ ...modes, [index]: "repaired" })}>{t("nw_question_repaired")}</Button>
          <Button size="sm" variant={modes[index] === "false_positive" ? "default" : "outline"} disabled={disabled} onClick={() => setModes({ ...modes, [index]: "false_positive" })}>{t("nw_question_false_positive")}</Button>
        </div>
        {repairBlocked && <p className="text-xs text-warn">{t("nw_question_repair_blocked")}</p>}
        {modes[index] && <div className="space-y-2">
          <Textarea aria-label={t(modes[index] === "repaired" ? "nw_question_repair_reason" : "nw_question_false_reason")} placeholder={t(modes[index] === "repaired" ? "nw_question_repair_reason" : "nw_question_false_reason")} value={reasons[index] ?? ""} disabled={disabled} onChange={(e) => setReasons({ ...reasons, [index]: e.target.value })} />
          <p className="text-xs text-muted-foreground">{t("nw_question_confirm_hint")}</p>
          <Button size="sm" disabled={disabled || !batch.review_revision || (reasons[index]?.trim().length ?? 0) < 10 || (modes[index] === "repaired" && repairBlocked)} onClick={() => confirm(batch.basis, batch.review_revision!, reasons[index], index, modes[index])}>{t("nw_question_confirm_one")}</Button>
        </div>}
      </>}
    </article>)}
    {!!review.resolved_questions?.length && <details className="text-sm"><summary className="cursor-pointer">{t("nw_question_history")} ({review.resolved_questions.length})</summary>{review.resolved_questions.map((item, i) => <div key={i} className="mt-2 space-y-1 rounded border p-2"><strong>{item.resolution === "false_positive" ? t("nw_question_false_positive") : item.resolution === "repaired" ? t("nw_question_repaired") : t("nw_question_history")}</strong>{item.questions.map((q, j) => <p key={j}>{q.replace(/utterances/gi, t("nw_question_dialogue"))}</p>)}<p>{item.reason}</p><p className="text-xs text-muted-foreground">{item.created_at}</p></div>)}</details>}
  </div>;
}
