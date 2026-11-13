import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { API } from "@/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogBody } from "@/components/ui/dialog";
import { errMsg } from "@/utils/async";
import { highlightedSource } from "./source-highlights";

export interface SourceTarget { basis: string; shotId?: string; segment?: number; utterance?: number }
export function SceneBatchSource({ projectName, basis, shotId, segment, utterance, shotLabels, close }: SourceTarget & { projectName: string; shotLabels?: Map<string, string>; close: () => void }) {
  const { t } = useTranslation("dashboard");
  const [value, setValue] = useState<Awaited<ReturnType<typeof API.getSceneBatchSource>> | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState(shotId ?? "");
  const [manualSelection, setManualSelection] = useState(false);
  const body = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let active = true;
    void API.getSceneBatchSource(projectName, basis).then((v) => { if (active) setValue(v); }).catch((e: unknown) => { if (active) setError(errMsg(e)); });
    return () => { active = false; };
  }, [projectName, basis]);
  const shot = value?.shots.find((s) => s.id === selected);
  const dialogues = shot?.dialogues.filter((d) => manualSelection || segment === undefined || (d.segment === segment && d.utterance === utterance)) ?? [];
  const ranges = dialogues.flatMap((d) => d.ranges);
  const parts = value ? highlightedSource(value.text, value.start, shot, ranges) : [];
  useEffect(() => {
    const target = body.current?.querySelector("[data-source-focus]") ?? body.current?.querySelector("mark");
    target?.scrollIntoView({ block: "center" });
  }, [value, selected, segment, utterance]);
  return <Dialog open onOpenChange={(open) => { if (!open) close(); }}><DialogContent size="xl">
    <DialogHeader><DialogTitle>{t("nw_batch_source_title")}{value && ` · ${value.note_title} · ${value.part}`}</DialogTitle><DialogDescription>{t("nw_source_highlight_hint")}</DialogDescription>
      {value && <p className="text-xs text-muted-foreground">{value.source_file} · {value.start}–{value.end}</p>}
      {value && <select className="mt-2 w-full rounded border bg-background p-2 text-sm" aria-label={t("nw_source_select_shot")} value={selected} onChange={(e) => { setSelected(e.target.value); setManualSelection(true); }}><option value="">{t("nw_batch_source")}</option>{value.shots.map((s) => <option key={s.id} value={s.id}>{shotLabels?.get(s.id) ?? s.id} · {s.title}</option>)}</select>}
      {shot && dialogues.length > 0 && !ranges.length && <p className="mt-2 text-xs text-warn">{t("nw_source_no_dialogue_match")}</p>}
    </DialogHeader>
    <DialogBody ref={body}>{error ? <p role="alert" className="text-sm text-destructive">{error}</p> : value ? <p className="font-editorial text-base leading-8 whitespace-pre-wrap">{parts.map((p) => p.focus || p.context ? <mark key={p.start} data-source-focus={p.focus ? "true" : undefined} className={p.focus ? "rounded bg-warn/35 font-semibold text-foreground underline decoration-2 underline-offset-4" : "rounded bg-primary/10 text-foreground"}>{p.text}</mark> : <span key={p.start}>{p.text}</span>)}</p> : <p role="status">{t("nw_task_preparing")}</p>}</DialogBody>
  </DialogContent></Dialog>;
}
