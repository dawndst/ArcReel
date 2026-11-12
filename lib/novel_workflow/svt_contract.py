"""One primary SVT per chapter Note; alternatives never count as ownership."""

from uuid import uuid4

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import store


def assignments(svts):
    result = {}
    for svt in svts:
        if svt.get("stale"):
            continue
        for note in svt["note_ids"]:
            if note in result and result[note] != svt["id"]:
                raise ValueError("一个 Note 不能同时主归属多个 SVT")
            result[note] = svt["id"]
    return result


def valid_svts(path, value, readings):
    if (
        not value
        or value.get("schema_version") != 2
        or value.get("rule_basis") != digest(store.effective_rule(path, "svt"))
    ):
        return []
    return [
        s
        for s in value["svts"]
        if not s.get("stale")
        and all(
            readings.get(i, {}).get("basis") == value.get("note_bases", {}).get(i) and i in readings
            for i in s["note_ids"]
        )
    ]


def adopt(path, project, note_id, candidate_id, expected):
    with project_metadata_lock(path):
        notebook = store.require_current(path, project, expected)
        readings = store.valid_readings(path, notebook)
        file = store.root(path) / "svts.json"
        if not file.exists():
            raise ValueError("请先完成 SVT 拆分")
        data = load_json(file)
        live = valid_svts(path, data, readings)
        ownership = assignments(live)
        current_id = ownership.get(note_id)
        candidate = next(
            (c for c in data.get("note_candidates", {}).get(note_id, []) if c["candidate_id"] == candidate_id), None
        )
        if not current_id or not candidate or candidate["basis"] != readings[note_id]["basis"]:
            raise ValueError("备选或原文依据已变化，请重新拆分后选择")
        previous = next(s for s in data["svts"] if s["id"] == current_id)
        target = next((s for s in live if s["id"] == candidate.get("existing_id")), None)
        if candidate.get("existing_id") and not target:
            raise ValueError("候选 SVT 已失效，请刷新备选")
        if target and target["id"] == current_id:
            return {"svt_id": current_id}
        snapshot = load_json(file)
        if target is None:
            target = {
                "id": uuid4().hex,
                "title": candidate["title"],
                "summary": candidate["summary"],
                "mainline_reason": candidate["reason"],
                "status": "open",
                "note_ids": [],
                "event_ids": [],
                "evidence": [],
                "climaxes": [],
                "payoffs": [],
                "dialogue_ids": [],
                "dialogues": [],
            }
            data["svts"].append(target)
        # Move the Note's facts as a unit; its explosions and dialogue remain paired with their source.
        moving_ids = {
            event
            for event, evidence in zip(previous["event_ids"], previous["evidence"], strict=True)
            if evidence["note_id"] == note_id
        }
        for event, evidence in list(zip(previous["event_ids"], previous["evidence"], strict=True)):
            if event in moving_ids and event not in target["event_ids"]:
                target["event_ids"].append(event)
                target["evidence"].append(evidence)
        keep = [(i, e) for i, e in zip(previous["event_ids"], previous["evidence"], strict=True) if i not in moving_ids]
        previous["event_ids"] = [i for i, _ in keep]
        previous["evidence"] = [e for _, e in keep]
        previous["note_ids"] = [i for i in previous["note_ids"] if i != note_id]
        target["note_ids"] = list(dict.fromkeys(target["note_ids"] + [note_id]))
        for kind in ("climaxes", "payoffs"):
            moved = [m for m in previous[kind] if set(m["note_ids"]) == {note_id}]
            mixed = [m for m in previous[kind] if note_id in m["note_ids"] and len(set(m["note_ids"])) > 1]
            if mixed:
                raise ValueError("存在跨 Note 爆点，请重新拆分后调整主归属，避免拆散场面与台词")
            target[kind] = list({digest(m): m for m in target[kind] + moved}.values())
            previous[kind] = [m for m in previous[kind] if note_id not in m["note_ids"]]
        for svt in (previous, target):
            svt["dialogues"] = list(
                {d["id"]: d for m in svt["climaxes"] + svt["payoffs"] for d in m["dialogues"]}.values()
            )
            svt["dialogue_ids"] = [d["id"] for d in svt["dialogues"]]
            svt["breakdown_status"] = "needs_review"
            svt["assignment_changed_at"] = now()
        data["svts"] = [s for s in data["svts"] if s["note_ids"]]
        data["note_assignments"] = assignments(data["svts"])
        # The old primary remains an explicit alternative, allowing a deliberate reversal.
        alternatives = [c for c in data["note_candidates"][note_id] if c["candidate_id"] != candidate_id]
        alternatives.append(
            {
                "candidate_id": uuid4().hex,
                "existing_id": current_id if previous["note_ids"] else None,
                "title": previous["title"],
                "summary": previous["summary"],
                "reason": "原主归属，供重新选择",
                "basis": readings[note_id]["basis"],
            }
        )
        data["note_candidates"][note_id] = alternatives
        store.write(store.root(path) / "history" / f"svt-{uuid4().hex}.json", snapshot)
        store.write(file, data)
        return {"svt_id": target["id"]}
