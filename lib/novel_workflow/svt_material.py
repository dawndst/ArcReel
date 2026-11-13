"""Edition-first SVT inputs with complete event coverage and exact dialogue anchors."""

import json
from copy import deepcopy

from pydantic import Field

from lib.novel_understanding.store import digest
from lib.novel_workflow.models import SVTBatch


class Proposal(SVTBatch):
    source_requests: list[str] = Field(
        default_factory=list,
        description="精简稿不足以判断因果、身份或爆点时，请求回看本批事件ID；请求时可不输出svts。",
    )


EVENT_FIELDS = (
    "id",
    "note_id",
    "title",
    "characters",
    "cause",
    "conflict",
    "action",
    "outcome",
    "claim_type",
    "source_kind",
    "perspective",
    "uncertainty_reason",
)
DIALOGUE_FIELDS = ("id", "speaker", "quote", "value", "claim_type", "source_kind", "perspective", "uncertainty_reason")


def compact_event(event):
    return {key: event[key] for key in EVENT_FIELDS if key in event}


def overlaps(a, b):
    return a["source_file"] == b["source_file"] and a["start"] < b["end"] and a["end"] > b["start"]


def prepare(batch, edition):
    passages = [p for part in edition["parts"] for p in part["passages"]]
    prose, rows, dialogues, originals = {}, [], {}, {}
    for event in batch:
        ev = event["evidence"]
        selected = [p for p in passages if overlaps(ev, p["evidence"])]
        row = compact_event(event)
        row["passage_ids"] = []
        for passage in selected:
            if not passage["text"]:
                continue
            key = digest([event["note_id"], passage["evidence"]])[:16]
            prose[key] = {
                "id": key,
                "note_id": event["note_id"],
                "text": passage["text"],
                "treatment": passage["treatment"],
                "source_span": passage["evidence"],
            }
            row["passage_ids"].append(key)
        # Missing/omitted or uncertain prose must not erase an indexed event.
        covered_until = ev["start"]
        for passage in sorted(selected, key=lambda p: p["evidence"]["start"]):
            span = passage["evidence"]
            if passage["text"] and span["start"] <= covered_until:
                covered_until = max(covered_until, span["end"])
        if (
            covered_until < ev["end"]
            or any(p["treatment"] == "uncertain" for p in selected)
            or event.get("claim_type", "unclassified") in {"unclassified", "inference"}
            or event.get("uncertainty_reason")
        ):
            originals[event["id"]] = {"event_id": event["id"], "evidence": ev}
        row["dialogue_ids"] = []
        for dialogue in event.get("dialogues", []):
            dialogues[dialogue["id"]] = {
                **{key: dialogue[key] for key in DIALOGUE_FIELDS if key in dialogue},
                "event_id": event["id"],
                "note_id": event["note_id"],
            }
            row["dialogue_ids"].append(dialogue["id"])
        rows.append(row)
    return {
        "events": rows,
        "edition_passages": list(prose.values()),
        "original_dialogues": list(dialogues.values()),
        "source_excerpts": list(originals.values()),
    }


def prompt(rules, direction, material, supplied):
    narrative = {k: v for k, v in material.items() if k != "events"}
    return (
        rules
        + "\n整章方向材料："
        + json.dumps(direction, ensure_ascii=False)
        + "\n精简稿与原句："
        + json.dumps(narrative, ensure_ascii=False)
        + "\n必须覆盖的本批事件ID（全部进入本Note唯一主归属event_ids）："
        + json.dumps([e["id"] for e in material["events"]])
        + "\n本批事件："
        + json.dumps(material["events"], ensure_ascii=False)
        + "\n可续接SVT："
        + json.dumps(supplied, ensure_ascii=False)
    )


async def generate(path, generator, rules, direction, batch, edition, supplied, validate):
    from lib.novel_workflow.service import ask

    material = prepare(batch, edition)
    ids = {e["id"] for e in batch}

    def first_check(value):
        if value.source_requests:
            if not set(value.source_requests) <= ids:
                raise ValueError("原文回查只能请求本批已提供的事件ID")
            return {"source_requests": list(dict.fromkeys(value.source_requests))}
        return validate(SVTBatch.model_validate(value.model_dump(exclude={"source_requests"})))

    first_prompt = prompt(rules, direction, material, supplied)
    result = await ask(path, generator, Proposal, first_prompt, first_check)
    requested = result.get("source_requests", [])
    if requested:
        material = deepcopy(material)
        excerpts = {e["event_id"]: e for e in material["source_excerpts"]}
        for event in batch:
            if event["id"] in requested:
                excerpts[event["id"]] = {"event_id": event["id"], "evidence": event["evidence"]}
        material["source_excerpts"] = list(excerpts.values())
        result = await ask(
            path,
            generator,
            SVTBatch,
            prompt(rules, direction, material, supplied)
            + "\n已补入所请求的连续原文。依据仍不足的部分保留未知，不编造解释；只输出有依据的爆点。",
            validate,
        )
    return result, {
        "mode": "edition_first",
        "input_chars": len(first_prompt),
        "passage_count": len(material["edition_passages"]),
        "event_count": len(batch),
        "dialogue_count": len(material["original_dialogues"]),
        "source_requests": requested,
        "source_excerpt_count": len(material["source_excerpts"]),
    }
