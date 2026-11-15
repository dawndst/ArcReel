import { DialogueCoveragePanel, type DecideDialogue } from "./DialogueCoveragePanel";
import { MomentCoverage } from "./MomentCoverage";
import { sceneLibraryOrder } from "./scene-library-order";
import type { ChapterNote, SceneLibraryBatch } from "@/types/novel-workflow";

export function AdaptationDecisionPanel({ batches, notes, disabled, decide, locate, }: {
  batches: SceneLibraryBatch[]; notes: ChapterNote[]; disabled: boolean; decide: DecideDialogue;
  locate: (id: string) => void;
}) {
  const current = sceneLibraryOrder(batches.filter((batch) => !batch.stale), notes).ordered;
  const { shotLabels } = sceneLibraryOrder(batches, notes);
  return <section className="space-y-4">
    <p className="text-sm text-muted-foreground">根据已有场镜查看内容覆盖并记录删改决定。人工取舍为可选操作；无需逐条处理后才能组集。</p>
    <MomentCoverage batches={current} selected={[]} locate={locate} />
    {!!current.length && <h2 className="font-bold">{notes.find((note) => note.id === current[0].note_id)?.title} · {current.reduce((n, b) => n + b.scenes.length, 0)} 场 · {current.reduce((n, b) => n + b.scenes.flatMap((scene) => scene.shots).length, 0)} 镜</h2>}
    {!current.length && <p className="text-sm text-muted-foreground">本章尚无当前有效场镜。生成场镜后即可查看内容覆盖。</p>}
    {current.map((batch) => <section key={batch.basis} className="space-y-3 rounded-xl border bg-card p-4">
      <DialogueCoveragePanel batch={batch} disabled={disabled} decide={decide} locate={locate} />
    </section>)}
  </section>;
}
