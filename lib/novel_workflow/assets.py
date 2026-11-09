"""Bridge evidence-grounded Note mentions into native project production assets.

Names are not replaced by future identities. Only equal names AND explicit scopes
are joined; unresolved generic identities stay local to their source Note.
"""

from copy import deepcopy
from pathlib import Path

from lib.artifacts.formal_write import project_metadata_lock
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import store
from lib.project.asset_codes import ensure_asset_codes
from lib.project.asset_types import asset_name_comparison_key, validate_asset_name

BUCKETS = {"character": "characters", "scene": "scenes", "prop": "props"}
GENERIC = {
    "男人",
    "女人",
    "少年",
    "少女",
    "老人",
    "男子",
    "女子",
    "士兵",
    "老师",
    "侍女",
    "路人",
    "守卫",
    "未知",
    "不明",
}


def entity_key(asset: dict, note_id: str) -> str:
    name = asset_name_comparison_key(asset["name"])
    scope = asset.get("identity_scope", "").strip()
    return digest([asset["kind"], name, scope, note_id if not scope and name in GENERIC else ""])


def synchronize(path: Path) -> dict:
    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        notebook = store.state(path)
        if not notebook:
            return {"registered": 0}
        store.require_current(path, project, notebook["source_basis"])
        readings = store.valid_readings(path, notebook)
        links = project.setdefault("note_asset_links", {})
        entities = project.setdefault("note_asset_entities", {})
        variants = project.setdefault("note_asset_variants", {})
        ensure_asset_codes(project)
        registered = 0
        for note in notebook["notes"]:
            for mention in readings.get(note["id"], {}).get("assets", []):
                key = entity_key(mention, note["id"])
                bucket = project.setdefault(BUCKETS[mention["kind"]], {})
                entity = entities.get(key)
                entry = next(((n, a) for n, a in bucket.items() if entity and a.get("asset_id") == entity), None)
                if entity and entry is None:
                    # A creator removed/merged this asset; reading must not resurrect it.
                    continue
                # Reuse an unclaimed native asset only on exact name, without a conflicting scope.
                if entry is None and not mention.get("identity_scope") and mention["name"] not in GENERIC:
                    match = next(
                        (
                            (n, a)
                            for n, a in bucket.items()
                            if asset_name_comparison_key(n) == asset_name_comparison_key(mention["name"])
                            and a.get("asset_id") not in entities.values()
                        ),
                        None,
                    )
                    if match:
                        entry = match
                        entities[key] = match[1]["asset_id"]
                if entry is None:
                    try:
                        name = validate_asset_name(mention["name"])
                    except ValueError:
                        continue
                    occupied = {
                        asset_name_comparison_key(n)
                        for b in (*BUCKETS.values(), "products")
                        for n in project.get(b, {})
                    }
                    original = name
                    suffix = 1
                    while asset_name_comparison_key(name) in occupied:
                        suffix += 1
                        name = f"{original}（{suffix}）"
                    bucket[name] = {"description": mention["description"], "note_managed": True}
                    ensure_asset_codes(project)
                    entry = name, bucket[name]
                    entities[key] = entry[1]["asset_id"]
                    registered += 1
                name, asset = entry
                variant = mention.get("variant", "").strip() if mention["kind"] == "character" else ""
                target = asset
                default_variant = project.get("note_asset_entity_variants", {}).get(key)
                if default_variant and not variant:
                    target = next(
                        (v for v in asset.get("derivatives", {}).values() if v.get("asset_id") == default_variant), None
                    )
                    if target is None:
                        continue
                if variant:
                    try:
                        validate_asset_name(variant)
                    except ValueError:
                        variant = ""
                    if variant:
                        variant_key = digest([key, variant])
                        prior = variants.get(variant_key)
                        table = asset.setdefault("derivatives", {})
                        target = next((v for v in table.values() if prior and v.get("asset_id") == prior), None)
                        if prior and target is None:
                            continue
                        if target is None:
                            target = table.setdefault(variant, {"description": mention["description"]})
                        ensure_asset_codes(project)
                        variants[variant_key] = target["asset_id"]
                links[mention["id"]] = {
                    "asset_id": target["asset_id"],
                    "entity_id": asset["entity_id"],
                    "asset_code": target["asset_code"],
                    "note_id": note["id"],
                }
        store.write(path / "project.json", project)
        return {"registered": registered, "linked": len(links)}


def reference(project: dict, mention: dict) -> dict:
    link = project.get("note_asset_links", {}).get(mention["id"])
    if not link:
        return {}
    for bucket in BUCKETS.values():
        for name, asset in project.get(bucket, {}).items():
            if asset.get("asset_id") == link["asset_id"]:
                return {**link, "asset_name": name}
            for variant, value in asset.get("derivatives", {}).items():
                if value.get("asset_id") == link["asset_id"]:
                    return {**link, "asset_name": name, "variant": variant}
    return {**link, "asset_missing": True}


def annotate(project: dict, reading: dict | None) -> dict | None:
    if reading is None:
        return None
    result = deepcopy(reading)
    result["assets"] = [{**a, **reference(project, a)} for a in reading.get("assets", [])]
    return result
