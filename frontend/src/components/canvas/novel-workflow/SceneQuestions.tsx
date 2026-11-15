import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { SceneLibraryBatch } from "@/types/novel-workflow";

export type ConfirmQuestion = (batch: string, revision: string, reason: string, index: number, resolution: "repaired" | "false_positive") => void;

export function SceneQuestions({ batch, disabled, confirm, locate, source, shotLabels }: {
  batch: SceneLibraryBatch; disabled: boolean; confirm?: ConfirmQuestion;
  locate: (id: string) => void; source: (shotId?: string) => void; shotLabels: Map<string, string>;
}) {
  const { t } = useTranslation("dashboard");
  const [reasons, setReasons] = useState<Record<number, string>>({});
  const [modes, setModes] = useState<Record<number, "repaired" | "false_positive">>({});
  const review = batch.review;
  if (!review) return null;
  const missing = batch.scenes.flatMap((s) => s.shots).filter((shot) => shot.segments.some((seg) => seg.utterances.some((u) => u.kind === "dialogue" && !u.speaker?.trim())));
  return <div className="space-y-3">
    {review.unresolved.map((question, index) => <article key={index} className="space-y-3 rounded border border-warn/40 p-3">
      <p className="text-sm font-medium">{index + 1}. {question.replace(/utterances/gi, t("nw_question_dialogue"))}</p>
      {review.version === 2 && <p className="rounded bg-muted p-3 text-sm leading-7">{review.issues?.filter((i) => i.status === "open" && i.blocking)[index]?.suggestion}</p>}
      <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => { const id = review.issues?.filter((i) => i.status === "open" && i.blocking)[index]?.shot_ids[0]; if (id) source(id); else source(); }}>{t("nw_batch_source")}</Button>{(review.version === 2 ? batch.scenes.flatMap((s) => s.shots).filter((s) => review.issues?.filter((i) => i.status === "open" && i.blocking)[index]?.shot_ids.includes(s.id)) : missing).map((shot) => <Button key={shot.id} size="sm" variant="outline" onClick={() => locate(shot.id)}>{t("nw_question_locate", { shot: shotLabels.get(shot.id) ?? shot.id })}</Button>)}</div>
      <p className="text-xs text-muted-foreground">{t("nw_question_hint")}</p>
      {confirm && <>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant={modes[index] === "repaired" ? "default" : "outline"} disabled={disabled} onClick={() => setModes({ ...modes, [index]: "repaired" })}>{t("nw_question_repaired")}</Button>
          <Button size="sm" variant={modes[index] === "false_positive" ? "default" : "outline"} disabled={disabled} onClick={() => setModes({ ...modes, [index]: "false_positive" })}>{t("nw_question_false_positive")}</Button>
        </div>
        {modes[index] && <div className="space-y-2">
          <Textarea aria-label={t(modes[index] === "repaired" ? "nw_question_repair_reason" : "nw_question_false_reason")} placeholder={t(modes[index] === "repaired" ? "nw_question_repair_reason" : "nw_question_false_reason")} value={reasons[index] ?? ""} disabled={disabled} onChange={(e) => setReasons({ ...reasons, [index]: e.target.value })} />
          <p className="text-xs text-muted-foreground">{t("nw_question_confirm_hint")}</p>
          <Button size="sm" disabled={disabled || !batch.review_revision || (reasons[index]?.trim().length ?? 0) < 10} onClick={() => confirm(batch.basis, batch.review_revision!, reasons[index], index, modes[index])}>{t("nw_question_confirm_item")}</Button>
        </div>}
      </>}
    </article>)}
    {review.issues?.filter((i) => i.status === "open" && !i.blocking).map((issue) => <article key={issue.id} className="rounded border p-3 text-sm"><strong>{t("nw_scene_reference_suggestion")} · {issue.shot_ids.map((id) => shotLabels.get(id) ?? id).join("、")}</strong><p className="mt-2">{issue.reason}</p><p className="mt-1 text-muted-foreground">{issue.suggestion}</p><div className="mt-2 flex gap-2">{issue.shot_ids.map((id) => <Button key={id} size="sm" variant="outline" onClick={() => locate(id)}>{t("nw_scene_locate", { shot: shotLabels.get(id) ?? id })}</Button>)}</div></article>)}
  </div>;
}
