"""Exact source spans shared by source navigation and local dialogue attribution."""

from lib.novel_workflow import chapters, store
from lib.novel_workflow.scene_library import catalog, valid_batch


def batch_source(path, project, basis):
    notebook = store.state(path)
    if not notebook:
        raise ValueError("No Notes")
    store.require_current(path, project, notebook["source_basis"])
    readings = store.valid_readings(path, notebook)
    batch = next((b for b in catalog(path)["batches"].values() if b["basis"] == basis), None)
    if not batch or not valid_batch(path, batch, notebook, readings):
        raise ValueError("场镜依据已变化，请刷新后查看原文")
    note = next(n for n in notebook["notes"] if n["id"] == batch["note_id"])
    chunk = chapters.chunks(path, project, note)[batch["part"]]
    shots = []
    for scene in batch["scenes"]:
        for shot in scene["shots"]:
            ev = shot["evidence"]
            dialogues = []
            for i, segment in enumerate(shot["segments"]):
                for j, utterance in enumerate(segment["utterances"]):
                    if utterance["kind"] != "dialogue":
                        continue
                    text = utterance["text"].strip().strip('「」『』“”"')
                    matches, cursor = [], 0
                    while text and (pos := chunk["text"].find(text, cursor)) >= 0:
                        matches.append({"start": chunk["start"] + pos, "end": chunk["start"] + pos + len(text)})
                        cursor = pos + len(text)
                    local = [r for r in matches if ev["start"] <= r["start"] < r["end"] <= ev["end"]]
                    dialogues.append(
                        {"segment": i, "utterance": j, "text": utterance["text"], "ranges": local or matches}
                    )
            shots.append(
                {
                    "id": shot["id"],
                    "title": shot["title"],
                    "start": ev["start"],
                    "end": ev["end"],
                    "dialogues": dialogues,
                }
            )
    return {**chunk, "note_title": note["title"], "part": batch["part"] + 1, "shots": shots}
