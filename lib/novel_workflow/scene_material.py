"""One chapter source catalogue shared by scene planning, shots, review and repair."""

from copy import deepcopy

from lib.episode.episode_sources import discover_sources
from lib.novel_workflow import assets, condensation, store, understanding
from lib.novel_workflow.common import digest
from lib.novel_workflow.stage_runner import ContractError
from lib.novel_workflow.storage import load_json
from lib.novel_workflow.svt_contract import valid_svts

CONTRACT_VERSION = 2


def asset_available(catalogue, asset, event_ids, scene_ids=None):
    """Mention order is not an entity's birth time; changed forms stay event-scoped."""
    horizon = catalogue.chunk(
        event_ids
        if asset["kind"] == "character" and (asset.get("variant") or asset.get("state"))
        else scene_ids or event_ids
    )
    source = catalogue.sources[asset["source_id"]]
    return source["source_file"] == horizon["source_file"] and source["start"] < horizon["end"]


class Catalogue:
    def __init__(self, path, project, note, reading, edition, svt):
        self.path, self.project, self.note = path, project, note
        self.reading, self.edition, self.svt = reading, edition, svt
        self.texts = {d.rel_path: d.text for d in discover_sources(path, project)}
        self.sources, self.events, self.dialogues, self.passages, self.assets = {}, {}, {}, {}, {}
        for event in sorted(reading["events"], key=lambda e: e["evidence"]["start"]):
            source = self.add_source(event["evidence"])
            self.events[event["id"]] = {
                **{
                    k: event.get(k, "")
                    for k in (
                        "id",
                        "title",
                        "cause",
                        "conflict",
                        "action",
                        "outcome",
                        "claim_type",
                        "perspective",
                        "uncertainty_reason",
                    )
                },
                "source_id": source,
                "dialogue_ids": [],
            }
            for line in event.get("dialogues", []):
                ref = self.add_source(line["evidence"])
                self.dialogues[line["id"]] = {
                    "id": line["id"],
                    "event_id": event["id"],
                    "source_id": ref,
                    "text": line["quote"],
                    "speaker": line.get("speaker", "未明确"),
                    "value": line.get("value", ""),
                    "claim_type": line.get("claim_type", "unverified"),
                }
                self.events[event["id"]]["dialogue_ids"].append(line["id"])
        for part in edition["parts"]:
            for passage in part["passages"]:
                ev = {**passage["evidence"], "note_id": note["id"]}
                source = self.add_source(ev)
                key = "TXT-" + digest([source, passage["text"]])[:18]
                self.passages[key] = {
                    "id": key,
                    "source_id": source,
                    "text": passage["text"],
                    "treatment": passage["treatment"],
                }
        for mention in assets.mentions(project, reading):
            if mention.get("source_kind") in {"annotation", "unknown"}:
                continue
            ref = assets.reference(project, mention)
            self.assets[mention["id"]] = {
                "id": mention["id"],
                "kind": mention["kind"],
                "name": mention["name"],
                "description": mention.get("description", ""),
                "claim_type": mention.get("claim_type", "unverified"),
                "appearance_context": mention.get("appearance_context", "unclassified"),
                "source_id": self.add_source(mention["evidence"]),
                "asset_name": ref.get("asset_name"),
                "asset_id": ref.get("asset_id"),
                "variant": ref.get("variant", ""),
                "state": ref.get("state", ""),
                "pending": bool(ref.get("asset_missing") or ref.get("asset_issue") or not ref.get("asset_name")),
            }
        self.story = svt.get("note_stories", {}).get(note["id"], {})
        self.moments = []
        for kind in ("climaxes", "payoffs"):
            for m in svt.get(kind, []):
                if note["id"] not in m["note_ids"]:
                    continue
                ids = [e for e in m["event_ids"] if e in self.events]
                self.moments.append(
                    {
                        "id": "MOM-" + digest([svt["id"], kind, m["event_ids"], m["dialogue_ids"], m["scene"]])[:20],
                        "kind": kind,
                        "event_ids": ids,
                        "scene": m["scene"]
                        if set(m["note_ids"]) == {note["id"]}
                        else "；".join(self.events[e]["action"] for e in ids),
                        "dialogue_ids": [d for d in m["dialogue_ids"] if d in self.dialogues],
                    }
                )
        self.basis = digest(
            [
                CONTRACT_VERSION,
                reading["basis"],
                edition["basis"],
                self.story,
                self.events,
                self.dialogues,
                self.moments,
            ]
        )

    def add_source(self, evidence):
        ev = {k: evidence[k] for k in ("source_file", "start", "end")}
        if not any(
            s["source_file"] == ev["source_file"] and s["start"] <= ev["start"] < ev["end"] <= s["end"]
            for s in self.note["sections"]
        ):
            raise ValueError("来源必须位于当前 Note，不能引用其他章节")
        ev["note_id"] = self.note["id"]
        text = self.texts[ev["source_file"]][ev["start"] : ev["end"]]
        if evidence.get("quote") is not None and evidence["quote"] != text:
            raise ValueError("已有证据与当前原文位置不一致，请核对 Note")
        key = "SRC-" + digest([self.note["basis"], ev])[:20]
        self.sources[key] = {**ev, "quote": text}
        return key

    def lookup(self, requested):
        unknown = set(requested) - set(self.sources)
        if unknown:
            raise ContractError([{"path": ["source_requests"], "message": "只能请求本章来源索引中的 ID"}])
        return {key: self.sources[key] for key in requested}

    def chunk(self, event_ids):
        refs = [self.sources[self.events[i]["source_id"]] for i in event_ids]
        refs.extend(self.sources[d["source_id"]] for d in self.dialogues.values() if d["event_id"] in event_ids)
        if len({r["source_file"] for r in refs}) != 1:
            raise ValueError("单场不能跨原文文件，请拆分场面")
        start, end = min(r["start"] for r in refs), max(r["end"] for r in refs)
        return {
            "note_id": self.note["id"],
            "source_file": refs[0]["source_file"],
            "start": start,
            "end": end,
            "text": self.texts[refs[0]["source_file"]][start:end],
        }

    def material(self, event_ids=None):
        planning = event_ids is None
        ids = list(event_ids or self.events)
        bounds_list = self.note["sections"] if planning else [self.chunk(ids)]
        bounds = bounds_list[0]
        passages = [
            p
            for p in self.passages.values()
            if any(self.overlaps(self.sources[p["source_id"]], b) for b in bounds_list)
        ]
        dialogues = [d for d in self.dialogues.values() if d["event_id"] in ids]
        refs = (
            {self.events[i]["source_id"] for i in ids}
            | ({d["source_id"] for d in dialogues} if not planning else set())
            | {p["source_id"] for p in passages}
        )
        known = understanding.production_context(self.path, [self.note["id"]], source_offset=bounds["start"])
        return {
            "note": {"id": self.note["id"], "title": self.note["title"]},
            "chapter_story": {k: self.story.get(k) for k in ("title", "summary", "advancement")} if planning else None,
            "edition": passages,
            "events": [
                {
                    **{k: v for k, v in self.events[i].items() if not planning or k != "dialogue_ids"},
                    **(
                        {
                            "available_asset_ids": [
                                a["id"] for a in self.assets.values() if asset_available(self, a, [i], ids)
                            ]
                        }
                        if not planning
                        else {}
                    ),
                }
                for i in ids
            ],
            "dialogues": []
            if planning
            else [
                {
                    **d,
                    "speaker_asset_ids": [
                        a["id"]
                        for a in self.assets.values()
                        if a["name"] == d["speaker"] and asset_available(self, a, [d["event_id"]], ids)
                    ],
                }
                for d in dialogues
            ],
            "moments": [
                {k: v for k, v in m.items() if not planning or k != "dialogue_ids"}
                for m in self.moments
                if set(m["event_ids"]) & set(ids)
            ],
            "assets": [
                {
                    k: v
                    for k, v in a.items()
                    if (
                        k in {"id", "kind", "name", "source_id", "claim_type", "appearance_context"}
                        if planning
                        else k not in {"asset_name", "asset_id"}
                    )
                }
                for a in self.assets.values()
                if any(
                    self.sources[a["source_id"]]["source_file"] == b["source_file"]
                    and self.sources[a["source_id"]]["end"] <= b["end"]
                    for b in bounds_list
                )
            ],
            "sources": [
                {"id": key, **{k: v for k, v in self.sources[key].items() if k != "quote"}} for key in sorted(refs)
            ],
            "known_before_scene": known["links"],
            "conclusion_constraints": [] if planning else self.constraints(bounds),
        }

    def constraints(self, bounds):
        review = self.reading.get("conclusion_review")
        return [
            {"id": c["id"], "status": c["status"], "production_constraint": c["production_constraint"]}
            for c in (review or {}).get("conclusions", [])
            if c.get("evidence")
            and all(e["note_id"] != self.note["id"] or e["end"] <= bounds["end"] for e in c["evidence"])
        ]

    @staticmethod
    def overlaps(a, b):
        return a["source_file"] == b["source_file"] and a["start"] < b["end"] and b["start"] < a["end"]


def load(path, note, reading=None):
    project = load_json(path / "project.json")
    notebook = store.state(path)
    readings = store.valid_readings(path, notebook)
    reading = deepcopy(reading or readings.get(note["id"]))
    if not reading:
        raise ValueError("请先完成本章 Note")
    from lib.novel_workflow.conclusions import effective_reading

    reading = effective_reading(path, note, reading)
    edition = condensation.load(path, note, reading)
    if not edition:
        raise ValueError("请先生成本章精简稿")
    svts = load_json(store.root(path) / "svts.json")
    svt = next((s for s in valid_svts(path, svts, readings) if note["id"] in s["note_ids"]), None)
    if not svt or svt.get("breakdown_status") == "needs_review" or not svt.get("note_stories", {}).get(note["id"]):
        raise ValueError("请先完成本章 SVT，主归属调整后须重新提炼本章剧情")
    return Catalogue(path, project, note, reading, edition, svt)
