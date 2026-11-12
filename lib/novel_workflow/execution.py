"""Editable, source-grounded shot execution plans and deterministic production checks."""

from copy import deepcopy
from uuid import uuid4

from pydantic import Field

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest, now
from lib.novel_workflow import store
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.scene_models import Segment
from lib.references.reference_catalog import split_derivative_reference

BUCKETS = {"character": "characters", "scene": "scenes", "prop": "props"}


class ShotEdit(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    segments: list[Segment] = Field(min_length=1, max_length=30)
    cut_before: list[int] = Field(
        default_factory=list, description="指定哪些SEG之前另开一个逻辑SH，索引从0开始，第一段不填"
    )


def asset(project, kind, reference):
    base, variant = split_derivative_reference(reference)
    root = project.get(BUCKETS[kind], {}).get(base, {})
    return root.get("derivatives", {}).get(variant, {}) if variant else root


def content_basis(shot):
    return digest(
        {
            k: v
            for k, v in shot.items()
            if k
            not in {
                "revision",
                "issues",
                "execution_checks",
                "execution_draft",
                "speaker_suggestions",
                "attribution_history",
                "edit_history",
            }
        }
    )


def inspect(shot, project):
    issues = []

    def add(code, segment=None, hard=False, **details):
        issues.append(
            {
                "id": digest([shot["id"], code, segment, details])[:24],
                "code": code,
                "shot_id": shot["id"],
                "segment": segment,
                "hard": hard,
                "details": details,
            }
        )

    if not shot.get("production"):
        add("design_missing", hard=True)
    camera = shot.get("production", {}).get("design", {}).get("camera_movement", "") + shot.get("production", {}).get(
        "design", {}
    ).get("shot_size", "")
    if any(word in camera for word in ("切近景", "切特写", "反打", "剪辑", "切换机位", "cut to", "reverse shot")):
        add("camera_cut")
    for index, seg in enumerate(shot["segments"]):
        visible = {n for key in ("characters_in_scene", "scenes", "props") for n in seg.get(key, [])}
        for field, kind in (("characters_in_scene", "character"), ("scenes", "scene"), ("props", "prop")):
            for name in seg.get(field, []):
                if not asset(project, kind, name).get("asset_id"):
                    add("asset_missing", index, True, name=name, kind=kind)
        for j, line in enumerate(seg["utterances"]):
            speaker = line.get("speaker")
            mode = line.get("delivery", "narration" if line["kind"] == "voiceover" else "unclassified")
            if line["kind"] == "dialogue" and not speaker:
                add("speaker_missing", index, True, utterance=j, text=line["text"])
            elif speaker and not asset(project, "character", speaker).get("asset_id"):
                add("speaker_asset_missing", index, True, utterance=j, name=speaker)
            if mode == "unclassified":
                add("delivery_unknown", index, False, utterance=j, text=line["text"])
            if mode == "on_screen" and speaker and speaker not in seg.get("characters_in_scene", []):
                add("speaker_not_visible", index, True, utterance=j, name=speaker)
            if (line["kind"] == "voiceover") != (mode == "narration"):
                add("delivery_kind", index, True, utterance=j)
            if line.get("origin") == "adaptation":
                add(
                    "adapted_dialogue",
                    index,
                    False,
                    utterance=j,
                    text=line["text"],
                    basis_quote=line.get("basis_quote", ""),
                )
        if not seg.get("start_frame") or not seg.get("end_frame"):
            add("frame_states", index)
        for state in seg.get("asset_states", []):
            if not asset(project, state["kind"], state["name"]).get("asset_id"):
                add("state_asset_missing", index, True, name=state["name"])
            if state["visibility"] != "visible" and state["name"] in visible:
                add("hidden_visible", index, True, name=state["name"])
            if state["visibility"] == "visible" and state["name"] not in visible:
                add("state_not_bound", index, True, name=state["name"])
        action = seg["scene_description"]
        for kind, bucket in BUCKETS.items():
            bound = set(seg.get({"character": "characters_in_scene", "scene": "scenes", "prop": "props"}[kind], []))
            bound = {n.split("/", 1)[0] for n in bound}
            declared = {
                s["name"] for s in seg.get("asset_states", []) if s["kind"] == kind and s["visibility"] != "visible"
            }
            declared = {n.split("/", 1)[0] for n in declared}
            covered = set(bound | declared)
            for key in bound | declared:
                item = project.get(bucket, {}).get(key, {})
                covered.update(
                    a for a in [*item.get("aliases", []), *item.get("note_source_names", [])] if isinstance(a, str)
                )
            for name, item in project.get(bucket, {}).items():
                aliases = [name, *item.get("aliases", []), *item.get("note_source_names", [])]
                # Literal use in action text is a question for the director, never an automatic appearance.
                terms = [n for n in aliases if isinstance(n, str) and len(n) >= 2]
                if any(n in action and n not in covered for n in terms) and name not in bound and name not in declared:
                    add("asset_in_action", index, False, name=name, kind=kind)
        if not seg.get("scenes"):
            add("background", index)
        if any(word in action for word in ("受伤", "斩断", "血", "清洗", "骑", "抓住", "隐匿", "附身")) and not seg.get(
            "asset_states"
        ):
            add("continuity", index)
    return issues


def editable(path, project, shot_id, expected, revision):
    from lib.novel_workflow.scene_library import catalog, valid_batch

    notebook = store.require_current(path, project, expected)
    readings = store.valid_readings(path, notebook)
    library = catalog(path)
    for batch in library["batches"].values():
        for scene in batch["scenes"]:
            for shot in scene["shots"]:
                if shot["id"] == shot_id:
                    if digest(shot) != revision or not valid_batch(path, batch, notebook, readings):
                        raise ValueError("镜头或原文依据已变化，请刷新后重试")
                    return notebook, readings, library, batch, scene, shot
    raise ValueError("镜头不存在")


def validate_edit(value, original, project):
    from lib.novel_workflow.evidence import locate

    compact = "".join(original.split())
    for segment in value.segments:
        for utterance in segment.utterances:
            needle = "".join(utterance.text.split()).strip('「」『』“”‘’"')
            if utterance.origin == "source" and needle not in compact:
                raise ValueError("对白不是当前原文的连续摘录；改编对白须明确标注并填写原文依据")
            if utterance.origin == "adaptation":
                if not utterance.basis_quote.strip():
                    raise ValueError("改编对白必须填写原文依据")
                locate(original, utterance.basis_quote)
            if utterance.speaker and not asset(project, "character", utterance.speaker).get("asset_id"):
                raise ValueError("说话人须选择已登记角色；未具名角色可先补录")
        for field, kind in (("characters_in_scene", "character"), ("scenes", "scene"), ("props", "prop")):
            if any(not asset(project, kind, n).get("asset_id") for n in getattr(segment, field)):
                raise ValueError("镜头资产必须来自当前资产库")
        for state in segment.asset_states:
            if not asset(project, state.kind, state.name).get("asset_id"):
                raise ValueError("状态约束须关联已登记资产")
    if len(set(value.cut_before)) != len(value.cut_before) or any(
        i <= 0 or i >= len(value.segments) for i in value.cut_before
    ):
        raise ValueError("剪辑切点须指向第二段及之后的现有片段，不能重复")
    return value.model_dump()


def update(path, shot_id, expected, revision, value, *, split=False):
    from lib.novel_workflow.scene_source import batch_source
    from lib.novel_workflow.shot_production import asset_bindings, dialogue_links, planning_inputs

    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        _, readings, library, batch, scene, shot = editable(path, project, shot_id, expected, revision)
        original = batch_source(path, project, batch["basis"])["text"]
        payload = validate_edit(value, original, project)
        rules = store.rule(path, "shot_production")
        ctx = batch.get("production_context")
        previous_shots = {s["id"]: s for sc in batch["scenes"] for s in sc["shots"]}
        was_current = bool(
            ctx
            and batch.get("production_basis")
            == planning_inputs(ctx, rules, previous_shots, project, readings[batch["note_id"]])[2]
        )
        store.write(store.root(path) / "history" / f"execution-edit-{uuid4().hex}.json", deepcopy(batch))
        old_index = scene["shots"].index(shot)
        cuts = payload.pop("cut_before")
        if split:
            cuts = list(range(1, len(payload["segments"])))
        shot.update(payload)
        shot.pop("execution_draft", None)
        changed = [shot]
        if cuts:
            if len(shot["segments"]) < 2:
                raise ValueError("至少两个片段才能拆成独立镜头")
            changed = []
            starts = [0, *sorted(cuts)]
            groups = [
                shot["segments"][begin:finish]
                for begin, finish in zip(starts, [*starts[1:], len(shot["segments"])], strict=True)
            ]
            for index, segments in enumerate(groups):
                item = deepcopy(shot)
                if index:
                    library["shot_counter"] = (
                        max(library.get("shot_counter", 0), max(int(s[3:]) for s in previous_shots)) + 1
                    )
                    item["id"] = f"SH-{library['shot_counter']:04}"
                item["title"] = shot["title"] + (f" · {index + 1}" if index else "")
                item["segments"] = segments
                if item.get("production"):
                    item["production"]["shot_id"] = item["id"]
                    item["production"]["moment_ids"] = []
                item["split_from"] = shot_id
                changed.append(item)
            scene["shots"][old_index : old_index + 1] = changed
            scene_index = batch["scenes"].index(scene)
            for rev in batch.get("review", {}).get("revisions", []):
                if rev["scene_index"] != scene_index:
                    continue
                if rev["shot_index"] > old_index:
                    rev["shot_index"] += len(changed) - 1
                elif rev["shot_index"] == old_index and rev.get("segment_index") is not None:
                    rev["superseded"] = True
                    rev["segment_index"] = 0
        for revision_item in batch.get("review", {}).get("revisions", []):
            if (
                revision_item["scene_index"] == batch["scenes"].index(scene)
                and revision_item["shot_index"] == old_index
            ):
                revision_item["superseded"] = True
        for item in changed:
            item.setdefault("edit_history", []).append({"at": now(), "actor": "human", "split": bool(cuts)})
            if item.get("production"):
                item["production"]["assets"] = asset_bindings(project, readings[batch["note_id"]], item)
                item["production"]["dialogue_sources"] = dialogue_links(readings[batch["note_id"]], item)
        if was_current:
            shots = {s["id"]: s for sc in batch["scenes"] for s in sc["shots"]}
            batch["production_basis"] = planning_inputs(ctx, rules, shots, project, readings[batch["note_id"]])[2]
        store.write(store.root(path) / "scene_library.json", library)
        return {"shot_ids": [s["id"] for s in changed]}
