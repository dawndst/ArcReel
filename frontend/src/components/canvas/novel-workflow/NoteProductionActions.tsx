import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogTitle } from "@/components/ui/dialog";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import type { ChapterNote, NovelWorkflow } from "@/types/novel-workflow";

export function noteProductionStatus(data: NovelWorkflow | null, notes: ChapterNote[]) {
  const svts = (data?.svts ?? []).filter((svt) => notes.some((n) => n.svt_id === svt.id));
  const batches = (data?.scene_batches ?? []).filter((b) => notes.some((n) => n.id === b.note_id));
  return {
    svts, batches,
    svtComplete: notes.length > 0 && !data?.stale && notes.every((n) => n.status === "read" && n.svt_status === "complete" && svts.some((s) => s.id === n.svt_id && !s.stale)),
    scenes: batches.reduce((count, b) => count + b.scenes.length, 0),
    shots: batches.reduce((count, b) => count + b.scenes.reduce((sum, s) => sum + s.shots.length, 0), 0),
    scenesForAll: notes.length > 0 && notes.every((n) => batches.some((b) => b.note_id === n.id)),
    scenesStale: batches.some((b) => b.stale || b.production_stale),
  };
}

export function NoteProductionActions({ data, notes, canSvt, canScenes, busy, run, viewSvt, viewScenes }: {
  data: NovelWorkflow; notes: ChapterNote[]; canSvt: boolean; canScenes: boolean; busy: boolean;
  run: (action: "svt" | "scenes", ids: string[]) => Promise<void>;
  viewSvt: (id: string) => void; viewScenes: (id: string) => void;
}) {
  const { t } = useTranslation(["dashboard", "common"]);
  const status = noteProductionStatus(data, notes);
  const [pending, setPending] = useState<{ action: "svt" | "scenes"; ids: string[]; titles: string[] } | null>(null);
  const open = (action: "svt" | "scenes") => {
    if (busy || !(action === "svt" ? canSvt : canScenes)) return;
    setPending({ action, ids: notes.map((n) => n.id), titles: notes.map((n) => n.title) });
  };
  const hasSvt = status.svts.length > 0;
  const hasScenes = status.batches.length > 0;
  const sameSelection = pending?.ids.join("|") === notes.map((n) => n.id).join("|");
  return <>
    {hasSvt ? <Button size="sm" variant="outline" onClick={() => viewSvt(status.svts[0].id)}>{t(status.svtComplete ? "dashboard:nw_view_svt_complete" : "dashboard:nw_view_svt_existing")}</Button>
      : <Button size="sm" variant="outline" disabled={!canSvt} onClick={() => void run("svt", notes.map((n) => n.id))}>{t("dashboard:nw_generate_svt")}</Button>}
    {hasScenes ? <Button size="sm" onClick={() => viewScenes(status.batches[0].basis)}>{t("dashboard:nw_view_scenes_count", { scenes: status.scenes, shots: status.shots })}</Button>
      : <Button size="sm" disabled={!canScenes} onClick={() => void run("scenes", notes.map((n) => n.id))}>{t("dashboard:nw_generate_scenes")}</Button>}
    {(hasSvt || hasScenes) && <DropdownMenu><DropdownMenuTrigger render={<Button size="sm" variant="ghost" disabled={busy} />}>{t("dashboard:nw_update_outputs")}</DropdownMenuTrigger><DropdownMenuContent>
      {hasSvt && <DropdownMenuItem disabled={!canSvt} onClick={() => open("svt")}>{t("dashboard:nw_reextract_svt")}</DropdownMenuItem>}
      {hasScenes && <DropdownMenuItem disabled={!canScenes} onClick={() => open("scenes")}>{t("dashboard:nw_update_scenes")}</DropdownMenuItem>}
    </DropdownMenuContent></DropdownMenu>}
    <Dialog open={pending !== null} onOpenChange={(value) => { if (!value && !busy) setPending(null); }}><DialogContent>
      <DialogTitle>{t(pending?.action === "svt" ? "dashboard:nw_reextract_svt" : "dashboard:nw_update_scenes")}</DialogTitle>
      <DialogDescription>{t(pending?.action === "svt" ? "dashboard:nw_reextract_svt_hint" : "dashboard:nw_update_scenes_hint")}</DialogDescription>
      <p className="text-sm">{pending?.titles.join("、")}</p>
      <DialogFooter><Button variant="outline" disabled={busy} onClick={() => setPending(null)}>{t("common:cancel")}</Button><Button disabled={busy || !sameSelection || !(pending?.action === "svt" ? canSvt : canScenes)} onClick={() => { if (pending && sameSelection && !busy) void run(pending.action, pending.ids).then(() => setPending(null)); }}>{t("dashboard:nw_confirm_update_outputs")}</Button></DialogFooter>
    </DialogContent></Dialog>
  </>;
}
