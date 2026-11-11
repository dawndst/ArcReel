import type { ChapterNote, SceneLibraryBatch } from "@/types/novel-workflow";

/** Display ordinals follow source order; stable IDs continue to address saved artifacts. */
export function sceneLibraryOrder(batches: SceneLibraryBatch[], notes: ChapterNote[]) {
  const noteOrder = new Map(notes.map((note) => [note.id, note.order]));
  const ordered = [...batches].sort((a, b) =>
    (noteOrder.get(a.note_id) ?? a.note_order ?? 0) - (noteOrder.get(b.note_id) ?? b.note_order ?? 0)
    || (a.part ?? 0) - (b.part ?? 0));
  const sceneLabels = new Map<string, string>();
  const shotLabels = new Map<string, string>();
  let sceneNumber = 0;
  let shotNumber = 0;
  for (const batch of ordered) {
    for (const scene of batch.scenes) {
      sceneLabels.set(scene.id, `SCN-${String(++sceneNumber).padStart(3, "0")}`);
      for (const shot of scene.shots) {
        shotLabels.set(shot.id, `SH-${String(++shotNumber).padStart(3, "0")}`);
      }
    }
  }
  return { ordered, sceneLabels, shotLabels };
}
