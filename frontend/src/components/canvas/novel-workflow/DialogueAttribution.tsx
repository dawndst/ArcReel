import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { LibraryShot } from "@/types/novel-workflow";
export function DialogueAttribution({ shot, segment, utterance, characters, disabled, attribute, source }: {
  shot: LibraryShot; segment: number; utterance: number; characters: string[]; disabled: boolean;
  attribute?: (shot: string, segment: number, utterance: number, speaker: string, revision: string) => void;
  source?: () => void;
}) {
  const { t } = useTranslation("dashboard");
  const suggestion = shot.speaker_suggestions?.items.find((s) => s.segment_index === segment && s.utterance_index === utterance);
  const canApply = suggestion?.speaker && characters.includes(suggestion.speaker);
  return <div className="mt-2 space-y-2 rounded border border-warn/50 bg-warn/10 p-3 text-foreground">
    <p className="text-xs">{t("nw_speaker_hint")}</p>
    {source && <Button size="sm" variant="outline" onClick={source}>{t("nw_dialogue_source")}</Button>}
    {suggestion && <div className="space-y-2 rounded border bg-card p-3 text-sm"><strong>{suggestion.speaker ? t("nw_speaker_ai_proposal", { speaker: suggestion.speaker }) : t("nw_speaker_ai_unknown")}</strong><p>{suggestion.reason}</p>{suggestion.source_quote && <blockquote className="border-l-2 border-primary/40 pl-3">{suggestion.source_quote}</blockquote>}{canApply && attribute && <Button size="sm" disabled={disabled || !shot.revision} onClick={() => attribute(shot.id, segment, utterance, suggestion.speaker!, shot.revision!)}>{t("nw_speaker_ai_adopt", { speaker: suggestion.speaker })}</Button>}</div>}
    {attribute && <select className="w-full rounded border bg-background p-2 text-sm" aria-label={t("nw_speaker_confirm")} value="" disabled={disabled || !shot.revision} onChange={(e) => { if (e.target.value && shot.revision) attribute(shot.id, segment, utterance, e.target.value, shot.revision); }}><option value="">{t("nw_speaker_confirm")}</option>{characters.map((name) => <option key={name} value={name}>{name}</option>)}</select>}
  </div>;
}
