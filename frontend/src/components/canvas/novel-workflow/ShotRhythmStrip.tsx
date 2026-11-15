import { type CSSProperties, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { LibraryShot } from "@/types/novel-workflow";

export function shotScale(value: string): number {
  const normalized = value.trim().toUpperCase();
  const names = [["远景", "全景", "大远景", "远全景", "ELS", "EWS", "LS", "WS"], ["中景", "MS"], ["中近景", "MCU"], ["近景", "CU"], ["特写", "细节", "特写/细节"], ["大特写", "ECU", "XCU"]];
  const index = names.findIndex((group) => group.includes(normalized));
  return index + 1;
}

export function ShotRhythmStrip({ shots, labels, locate }: {
  shots: LibraryShot[]; labels: Map<string, string>; locate: (id: string) => void;
}) {
  const { t } = useTranslation("dashboard");
  const heading = useId();
  const [active, setActive] = useState<string | null>(null);
  const durations = shots.map((shot) => shot.segments.reduce((sum, segment) => sum + Math.max(0, segment.duration_seconds), 0));
  const total = durations.reduce((sum, seconds) => sum + seconds, 0);
  if (!shots.length) return null;
  return <section aria-labelledby={heading} className="rhythm-strip min-w-0 space-y-3 rounded-xl border bg-card p-4 shadow-xs">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><h3 id={heading} className="text-sm font-bold">{t("nw_rhythm_title")}</h3><span className="text-xs tabular-nums text-muted-foreground">{t("nw_rhythm_total", { count: shots.length, seconds: total })}</span></div>
    <p className="text-xs leading-5 text-muted-foreground">{t("nw_rhythm_hint")}</p>
    <div className="relative overflow-x-auto scroll-fade-x p-1">
      <div className="min-w-(--strip-width)" style={{ "--strip-width": `${Math.max(280, total * 5, shots.length * 36)}px` } as CSSProperties}><div className="flex gap-0.5">
        {shots.map((shot, index) => {
          const size = shot.production?.design.shot_size ?? "";
          const description = `${labels.get(shot.id) ?? shot.id} · ${shot.title} · ${durations[index]}s · ${size || t("nw_rhythm_scale_0")}`;
          return <Tooltip key={shot.id}><TooltipTrigger render={<button type="button" />} className="rhythm-shot focus-ring relative min-w-0 basis-0 grow-(--shot-duration) overflow-hidden rounded-sm border border-input px-1 py-3 text-center font-mono text-xs font-semibold" data-scale={shotScale(size)} style={{ "--shot-duration": durations[index] || 1 } as CSSProperties} aria-label={description} aria-current={active === shot.id ? "true" : undefined} onClick={() => { setActive(shot.id); locate(shot.id); }}>
            <span className="block truncate">{labels.get(shot.id) ?? shot.id}</span>
          </TooltipTrigger><TooltipContent>{description}</TooltipContent></Tooltip>;
        })}
      </div>
      <div className="mt-1 flex justify-between text-xs tabular-nums text-muted-foreground"><span>0s</span><span>{total}s</span></div></div>
    </div>
    <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">{[1, 2, 3, 4, 5, 6, 0].map((scale) => <span key={scale} className="inline-flex items-center gap-1.5"><span aria-hidden="true" className="rhythm-shot size-3 rounded-sm border border-input" data-scale={scale} />{t(`nw_rhythm_scale_${scale}`)}</span>)}</div>
  </section>;
}
