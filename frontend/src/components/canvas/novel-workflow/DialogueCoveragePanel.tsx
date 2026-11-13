import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { SceneLibraryBatch } from "@/types/novel-workflow";

export type DecideDialogue = (batch: string, revision: string, dialogue: string, decision: "omit" | "restore", reason: string) => void;

export function DialogueCoveragePanel({ batch, disabled, decide, locate }: { batch: SceneLibraryBatch; disabled: boolean; decide?: DecideDialogue; locate: (shot: string) => void }) {
  const { t } = useTranslation("dashboard");
  const [editing, setEditing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const coverage = batch.dialogue_coverage;
  if (!coverage) return null;
  return <details className="space-y-3 rounded-lg border p-3">
    <summary className="cursor-pointer font-semibold">{t("nw_dialogue_coverage")}</summary>
    <p className="text-xs text-muted-foreground">{t("nw_dialogue_coverage_hint")}</p>
    <div className="flex flex-wrap gap-3 text-sm">{(["retained", "partial", "unassigned", "omitted"] as const).map((status) => <span key={status}>{t(`nw_dialogue_${status}`)} {coverage.counts[status]}</span>)}</div>
    {coverage.entries.map((entry) => <article key={entry.dialogue_id} className="space-y-2 rounded border p-3 text-sm">
      <p className="font-semibold">{t(`nw_dialogue_${entry.status}`)} · {entry.speaker || t("nw_speaker_pending")}</p>
      <blockquote className="whitespace-pre-wrap border-l-2 pl-2">{entry.quote}</blockquote>
      <p>{t("nw_dialogue_purposes")}：{entry.purposes.join("、") || t("nw_dialogue_none")}</p>
      <div className="flex flex-wrap gap-2">{entry.locations.map((location) => <Button key={`${location.shot_id}:${location.segment_index}:${location.utterance_index}`} size="sm" variant="outline" onClick={() => locate(location.shot_id)}>{location.shot_id} · SEG{location.segment_index + 1} · {t("nw_dialogue_line", { number: location.utterance_index + 1 })}</Button>)}</div>
      {entry.reason && <p className="text-muted-foreground">{t("nw_dialogue_reason")}：{entry.reason}</p>}
      {decide && entry.status !== "retained" && <Button size="sm" variant="outline" disabled={disabled} onClick={() => { setEditing(entry.dialogue_id); setReason(""); }}>{t(entry.status === "omitted" ? "nw_dialogue_restore" : "nw_dialogue_omit")}</Button>}
      {editing === entry.dialogue_id && <div className="space-y-2">
        <Textarea aria-label={t("nw_dialogue_reason")} placeholder={t("nw_dialogue_reason_hint")} value={reason} onChange={(event) => setReason(event.target.value)} />
        <div className="flex gap-2"><Button size="sm" disabled={disabled || reason.trim().length < 10} onClick={() => { if (disabled || reason.trim().length < 10) return; decide?.(batch.basis, coverage.revision, entry.dialogue_id, entry.status === "omitted" ? "restore" : "omit", reason.trim()); setEditing(null); }}>{t("nw_dialogue_save")}</Button><Button size="sm" variant="outline" onClick={() => setEditing(null)}>{t("nw_dialogue_cancel")}</Button></div>
      </div>}
    </article>)}
  </details>;
}
