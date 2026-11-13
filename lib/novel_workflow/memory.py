"""Evidence ledger derived from immutable readings, sliced at a reveal boundary."""

from __future__ import annotations

import json
from itertools import zip_longest

from lib.novel_understanding.store import digest
from lib.novel_workflow import store
from lib.novel_workflow.assets import mentions
from lib.novel_workflow.storage import load_json

BUCKETS = ("assets", "changes", "events", "aliases", "relations", "threads", "highlights")


def records(reading):
    return [item for key in BUCKETS for item in reading.get(key, [])]


def ledger(path, notebook, *, through=None, extra=(), readings=None):
    items = []
    project = load_json(path / "project.json") if (path / "project.json").exists() else {}
    bases = {}
    readings = (
        readings
        if readings is not None
        else store.valid_readings(path, notebook, before=through + 1 if through is not None else None)
    )
    for note in notebook["notes"]:
        if through is not None and note["order"] > through:
            break
        reading = readings.get(note["id"])
        if reading:
            bases[note["id"]] = reading["basis"]
            for key in BUCKETS:
                items.extend(
                    {**v, "bucket": key, "note_id": note["id"], "order": note["order"]}
                    for v in (mentions(project, reading) if key == "assets" else reading.get(key, []))
                )
    for reading in extra:
        for key in BUCKETS:
            items.extend(
                {**v, "bucket": key, "note_id": v["evidence"]["note_id"], "order": through or 0}
                for v in reading.get(key, [])
            )
    items = list({v["id"]: v for v in items}.values())
    aliases = [
        v
        for v in items
        if v["bucket"] == "aliases"
        and v.get("claim_type") == "fact"
        and v.get("source_kind") == "narrative"
        and v.get("source_kind") != "annotation"
    ]
    people = {}
    for item in items:
        if item["bucket"] != "assets" or item["kind"] != "character":
            continue
        name, scope = item["name"], item.get("identity_scope", "")
        matches = {a["name"] for a in aliases if a["alias"] == name and a.get("identity_scope", "") == scope}
        if len(matches) == 1:
            name = next(iter(matches))
        identity = digest([name, scope])[:24]
        person = people.setdefault(
            identity,
            {
                "id": identity,
                "name": name,
                "identity_scope": scope,
                "aliases": [],
                "appear": [],
                "mentions": [],
                "changes": [],
                "relations": [],
            },
        )
        person["mentions"].append(item)
        if item["note_id"] not in person["appear"]:
            person["appear"].append(item["note_id"])
    for person in people.values():
        person["aliases"] = [
            a
            for a in aliases
            if a["name"] == person["name"] and a.get("identity_scope", "") == person["identity_scope"]
        ]
    for person in people.values():
        names = {person["name"], *(a["alias"] for a in person["aliases"])}
        # Ambiguous names never attach a state to one of several identities silently.
        ambiguous = {
            n
            for n in names
            if sum(n == p["name"] or any(a["alias"] == n for a in p["aliases"]) for p in people.values()) > 1
        }
        person["changes"] = [v for v in items if v["bucket"] == "changes" and v["character"] in names - ambiguous]
        person["relations"] = [v for v in items if v["bucket"] == "relations" and v["subject"] in names - ambiguous]
    threads = [v for v in items if v["bucket"] == "threads"]
    seeds = [
        {**v, "resolutions": [r for r in threads if r["kind"] == "resolution" and r.get("seed_id") == v["id"]]}
        for v in threads
        if v["kind"] == "seed"
    ]
    return {
        "note_bases": bases,
        "through": through,
        "characters": list(people.values()),
        "aliases": aliases,
        "relations": [v for v in items if v["bucket"] == "relations"],
        "changes": [v for v in items if v["bucket"] == "changes"],
        "threads": seeds,
        "setting_records": [v for v in items if v["bucket"] == "assets" and v["kind"] in {"scene", "prop"}],
        "unmatched_resolutions": [v for v in threads if v["kind"] == "resolution" and not v.get("seed_id")],
    }


def context(ledger, text, budget=10000):
    entries = []
    for person in ledger["characters"]:
        names = [person["name"], *(a["alias"] for a in person["aliases"])]
        if any(name in text for name in names):
            entries.extend(
                person["aliases"]
                + person["mentions"][:1]
                + person["mentions"][-2:]
                + person["changes"]
                + person["relations"]
            )
    # Older stable settings and object handovers must not disappear behind recent emotions.
    entries.extend(v for v in ledger.get("setting_records", []) if v.get("name", "") in text)
    entries = list({v["id"]: v for v in entries}.values())

    def relevance(value):
        description = " ".join(
            str(value.get(k, "")) for k in ("description", "before", "after", "relation", "identity_scope")
        )
        score = sum(description[i : i + 2] in text for i in range(max(0, len(description) - 1)))
        return (value.get("dimension") not in {"emotion", "knowledge"}, score)

    entries.sort(key=relevance, reverse=True)
    # Pending threads remain eligible even when no character's name occurs verbatim.
    pending = [v for v in ledger["threads"] if not v["resolutions"]]
    pending.sort(
        key=lambda v: sum(v["description"][i : i + 2] in text for i in range(max(0, len(v["description"]) - 1))),
        reverse=True,
    )
    entries = [item for pair in zip_longest(entries, pending) for item in pair if item is not None]
    selected, size = [], 0
    for value in entries:
        encoded = json.dumps(value, ensure_ascii=False)
        if size + len(encoded) <= budget:
            selected.append(value)
            size += len(encoded)
    return {"records": selected, "omitted_count": len(entries) - len(selected)}
