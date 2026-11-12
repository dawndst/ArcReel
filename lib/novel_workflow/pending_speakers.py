"""Explicit identity placeholders for reference assembly, never inferred story identities."""

from lib.novel_understanding.store import digest
from lib.project.asset_codes import ensure_asset_codes


def register(project, notebook, shot, segment, utterance):
    line = shot["segments"][segment]["utterances"][utterance]
    key = digest([shot["id"], segment, utterance, line["text"]])
    characters = project.setdefault("characters", {})
    for name, asset in characters.items():
        if asset.get("pending_reference", {}).get("key") == key:
            return name
    name = f"待定说话角色-{shot['id']}-SEG{segment + 1}-U{utterance + 1}"
    if name in characters:
        name += "-" + key[:6]
    note = next(n for n in notebook["notes"] if n["id"] == shot["evidence"]["note_id"])
    characters[name] = {
        "description": "参考编排中的待定说话角色。真实身份、姓名及外观尚未确认，不代表原文已明确的人物事实；后续可人工改绑或合并资产。",
        "identity_status": "pending",
        "pending_reference": {
            "key": key,
            "shot_id": shot["id"],
            "segment": segment,
            "utterance": utterance,
            "text": line["text"],
            "original_speaker": line.get("speaker"),
            "evidence": shot["evidence"],
        },
        "first_note": {"id": note["id"], "order": note["order"], "title": note["title"]},
    }
    ensure_asset_codes(project)
    return name
