"""Propagate explicit asset identity decisions to unresolved scene references, without LLM work."""

from copy import deepcopy

from lib.artifacts.formal_write import project_metadata_lock
from lib.novel_workflow import assets, store
from lib.novel_workflow.common import digest
from lib.novel_workflow.scene_inspection import basis, shot_inputs
from lib.novel_workflow.storage import load_json

FIELDS = {"character": "characters_in_scene", "scene": "scenes", "prop": "props"}


def resolved(project, mention):
    ref = assets.reference(project, mention)
    if (
        not ref.get("asset_name")
        or ref.get("asset_missing")
        or (ref.get("asset_issue") and ref.get("asset_issue_blocking", True))
    ):
        return None
    item = project.get(assets.BUCKETS[mention["kind"]], {}).get(ref["asset_name"], {})
    if ref.get("variant"):
        item = item.get("derivatives", {}).get(ref["variant"], {})
    return ref if item.get("asset_id") == ref.get("asset_id") else None


def refresh(path):
    from lib.novel_workflow.scene_library import catalog
    from lib.novel_workflow.shot_production import asset_bindings, dialogue_links

    if not (store.root(path) / "scene_library.json").exists():
        return 0
    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        book = store.state(path)
        readings = store.valid_readings(path, book)
        library = catalog(path)
        changed = 0
        for batch in library["batches"].values():
            reading = readings.get(batch["note_id"])
            if (
                batch.get("pipeline_version") != 2
                or not reading
                or batch["source_basis"] != book["source_basis"]
                or batch["note_bases"].get(batch["note_id"]) != reading["basis"]
            ):
                continue
            mentions = {m["id"]: m for m in assets.mentions(project, reading)}
            refs = {key: resolved(project, m) for key, m in mentions.items()}
            lines = {d["id"]: d for e in reading.get("events", []) for d in e.get("dialogues", [])}
            for scene in batch["scenes"]:
                for shot in scene["shots"]:
                    before = deepcopy(shot)
                    original_input = next(
                        s for s in shot_inputs({"scenes": [{"shots": [before]}]}) if s["id"] == shot["id"]
                    )
                    pending = []
                    for item in shot.get("pending_asset_refs", []):
                        ref = refs.get(item["source_asset_id"])
                        indexes = (
                            [item["segment"]]
                            if "segment" in item
                            else [
                                i
                                for i, seg in enumerate(shot.get("reference_draft", {}).get("segments", []))
                                if item["source_asset_id"] in seg.get("visible_asset_ids", [])
                            ]
                        )
                        applied = False
                        for index in indexes:
                            if not ref or not 0 <= index < len(shot["segments"]):
                                continue
                            field = FIELDS[item["kind"]]
                            names = shot["segments"][index].get(field, [])
                            if item["name"] not in names:
                                continue
                            target = ref["asset_name"] + (
                                f"/{ref['variant']}" if ref.get("variant") and item["kind"] == "character" else ""
                            )
                            shot["segments"][index][field] = list(
                                dict.fromkeys(target if n == item["name"] else n for n in names)
                            )
                            for line in shot["segments"][index].get("utterances", []):
                                if line.get("delivery") == "on_screen" and line.get("speaker") == item["name"]:
                                    line["speaker"] = target
                            applied = True
                        if not applied:
                            pending.append(item)
                    if "pending_asset_refs" in shot:
                        shot["pending_asset_refs"] = pending
                    for link in shot.get("source_dialogue_uses", []):
                        si, ui = link["segment"], link["utterance"]
                        if si >= len(shot["segments"]) or ui >= len(shot["segments"][si]["utterances"]):
                            continue
                        segment = shot["segments"][si]
                        utterance = segment["utterances"][ui]
                        line = lines.get(link["dialogue_id"])
                        if utterance.get("speaker") or not line or utterance["text"] != line["quote"]:
                            continue
                        names = {
                            ref["asset_name"]
                            for key, ref in refs.items()
                            if ref
                            and mentions[key]["kind"] == "character"
                            and mentions[key]["name"] == line.get("speaker")
                        }
                        if len(names) == 1:
                            name = names.pop()
                            utterance["speaker"] = next(
                                (
                                    n
                                    for n in segment.get("characters_in_scene", [])
                                    if n == name or n.startswith(name + "/")
                                ),
                                name,
                            )
                    if shot == before:
                        continue
                    shot["production"]["assets"] = asset_bindings(project, reading, shot)
                    shot["production"]["dialogue_sources"] = dialogue_links(reading, shot)
                    reviewed = batch.get("inspection_shots", {})
                    if reviewed.get(shot["id"]) == digest(original_input):
                        reviewed[shot["id"]] = digest(shot_inputs({"scenes": [{"shots": [shot]}]})[0])
                    changed += 1
            if batch.get("inspection_rule_basis"):
                batch["inspection_basis"] = basis(batch, batch["inspection_rule_basis"])
        if changed:
            store.write(store.root(path) / "scene_library.json", library)
        return changed
