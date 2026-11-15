import { CraftPanel, type SaveCraft } from "./CraftPanel";
import { DialogueCoveragePanel, type DecideDialogue } from "./DialogueCoveragePanel";
import { MomentCoverage } from "./MomentCoverage";
import { sceneLibraryOrder } from "./scene-library-order";
import type { ChapterNote, NoteEvidence, SceneLibraryBatch } from "@/types/novel-workflow";

export function AdaptationDecisionPanel({ batches, notes, disabled, save, decide, locate, source }: {
  batches: SceneLibraryBatch[]; notes: ChapterNote[]; disabled: boolean; save: SaveCraft; decide: DecideDialogue;
  locate: (id: string) => void; source: (batch: string, range?: NoteEvidence) => void;
}) {
  const current = batches.filter((batch) => !batch.stale);
  const { shotLabels } = sceneLibraryOrder(batches, notes);
  return <section className="space-y-4">
    <p className="text-sm text-muted-foreground">根据已有场镜查看内容覆盖并记录删改决定。人工取舍为可选操作；无需逐条处理后才能组集。</p>
    <MomentCoverage batches={current} selected={[]} locate={locate} />
    {current.map((batch) => <section key={batch.basis} className="space-y-3 rounded-xl border bg-card p-4">
      <h2 className="font-bold">{notes.find((note) => note.id === batch.note_id)?.title} · {batch.scenes.flatMap((scene) => scene.shots).length} 镜</h2>
      <CraftPanel mode="decisions" batch={batch} disabled={disabled} labels={shotLabels} save={save} locate={locate} source={(_shot, range) => source(batch.basis, range)} />
      <DialogueCoveragePanel batch={batch} disabled={disabled} decide={decide} locate={locate} />
    </section>)}
  </section>;
}
