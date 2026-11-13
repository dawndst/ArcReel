"""Exact source spans shared by source navigation and local dialogue attribution."""

from lib.novel_understanding.store import digest
from lib.novel_workflow import chapters, store
from lib.novel_workflow.scene_library import catalog


def batch_source(path, project, basis):
    notebook = store.state(path)
    if not notebook:
        raise ValueError("No Notes")
    batch = next((b for b in catalog(path)["batches"].values() if b["basis"] == basis), None)
    if not batch:
        raise ValueError("场镜不存在")
    note = next((n for n in notebook["notes"] if n["id"] == batch["note_id"]), None)
    chunk = source_chunk(path, project, batch, notebook)
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
    return {**chunk, "note_title": note["title"] if note else "历史章节", "part": batch["part"] + 1, "shots": shots}


def source_chunk(path, project, batch, notebook=None):
    """Read immutable source independently of prompt/reading/production freshness.

    Historical batches without snapshots are allowed only against the identical
    original source digest. Never relocate old offsets into a replacement book.
    """
    snapshot = batch.get("source_snapshot")
    if snapshot:
        chunk = snapshot["chunk"]
        if snapshot.get("digest") != digest(chunk) or chunk["end"] - chunk["start"] != len(chunk["text"]):
            raise ValueError("历史原文快照校验失败，不能使用不可靠的依据")
        return chunk
    notebook = notebook or store.state(path)
    if not notebook or chapters.index(path, project)["source_basis"] != batch["source_basis"]:
        raise ValueError("原著文件已被替换，且此旧场镜没有原文快照；请恢复原文件后回看，不能套用新原文")
    note = next((n for n in notebook["notes"] if n["id"] == batch["note_id"]), None)
    if not note:
        raise ValueError("原章节已不在目录中，且没有历史原文快照")
    chunks = chapters.chunks(path, project, note)
    # source_start survives changes in batch order; part alone is not a source identity.
    chunk = next((c for c in chunks if c["start"] == batch.get("source_start")), None)
    if chunk is None and batch.get("source_start") is None and batch["part"] < len(chunks):
        chunk = chunks[batch["part"]]
    if chunk is None:
        raise ValueError("原文分块位置已变化，无法可靠恢复旧片段")
    for scene in batch["scenes"]:
        for shot in scene["shots"]:
            ev = shot["evidence"]
            start, end = ev["start"] - chunk["start"], ev["end"] - chunk["start"]
            if (
                ev["source_file"] != chunk["source_file"]
                or not 0 <= start < end <= len(chunk["text"])
                or chunk["text"][start:end] != ev["quote"]
            ):
                raise ValueError("镜头原文位置与保存的引句不一致，不能错误定位")
    return chunk


def snapshot(chunk):
    value = {k: chunk[k] for k in ("source_file", "note_id", "start", "end", "text")}
    return {"chunk": value, "digest": digest(value)}
