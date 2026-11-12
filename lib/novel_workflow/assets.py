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
from lib.project.asset_codes import ensure_asset_codes, keep_first_note
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
        issues = project.setdefault("note_asset_issues", {})
        resolutions = project.setdefault("note_asset_resolutions", {})
        ensure_asset_codes(project)
        for bucket in BUCKETS.values():
            for asset in project.get(bucket, {}).values():
                asset.pop("first_note", None)
                for variant in asset.get("derivatives", {}).values():
                    variant.pop("first_note", None)
        registered = 0
        active_visuals = {}
        for note in notebook["notes"]:
            for mention in sorted(
                readings.get(note["id"], {}).get("assets", []),
                key=lambda m: (m["evidence"].get("start", 0), m["evidence"].get("end", 0)),
            ):
                if mention.get("source_kind") == "annotation" or mention.get("claim_type") in {
                    "inference",
                    "statement",
                    "adaptation",
                }:
                    continue
                previous_issue = issues.pop(mention["id"], None)
                resolution = resolutions.get(mention["id"], {})
                key = entity_key(mention, note["id"])
                bucket = project.setdefault(BUCKETS[mention["kind"]], {})
                anchor = links.get(mention.get("same_entity_as", ""))
                prior_link = links.get(mention["id"], {})
                blocking = (
                    previous_issue.get("blocking", not bool(prior_link)) if previous_issue else not bool(prior_link)
                )
                entity = resolution.get("entity_id") or (
                    None
                    if resolution.get("create_new")
                    else (anchor["entity_id"] if anchor else prior_link.get("entity_id") or entities.get(key))
                )
                if anchor and not any(a.get("asset_id") == anchor["entity_id"] for a in bucket.values()):
                    issues[mention["id"]] = {"code": "identity_anchor_invalid", "candidates": [], "blocking": True}
                    continue
                if entity:
                    entities[key] = entity
                entry = next(((n, a) for n, a in bucket.items() if entity and a.get("asset_id") == entity), None)
                if entity and entry is None:
                    # A creator removed/merged this asset; reading must not resurrect it.
                    continue
                if entry is not None:
                    entities[key] = entry[1]["asset_id"]
                if entry is None and not entity and not resolution.get("create_new") and mention["name"] not in GENERIC:
                    candidates = [
                        {"entity_id": a["asset_id"], "name": n, "asset_code": a["asset_code"]}
                        for n, a in bucket.items()
                        if any(
                            asset_name_comparison_key(raw) == asset_name_comparison_key(mention["name"])
                            for raw in [n, *a.get("note_source_names", [])]
                        )
                        and a.get("asset_id") in entities.values()
                    ]
                    if candidates:
                        issues[mention["id"]] = {
                            "code": "identity_ambiguous",
                            "candidates": candidates,
                            "blocking": True,
                        }
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
                if resolution.get("create_new"):
                    resolution["entity_id"] = asset["asset_id"]
                names = asset.setdefault("note_source_names", [])
                if mention["name"] not in names:
                    names.append(mention["name"])
                variant = mention.get("variant", "").strip()
                variant_kind = resolution.get("variant_kind", mention.get("variant_kind", "unclassified"))
                variant = resolution.get("variant_name", variant)
                context = resolution.get(
                    "appearance_context",
                    mention.get("appearance_context", "vision" if mention.get("claim_type") == "vision" else "current"),
                )
                performance = variant if variant_kind == "performance" else ""
                state = resolution.get("asset_state", "")
                if mention["kind"] != "character" and variant_kind == "visual":
                    state = variant
                    variant = ""
                if variant_kind in {"performance", "none"}:
                    variant = ""
                visual_scope = (asset["entity_id"], context)
                target = active_visuals.get(visual_scope, asset) if variant_kind in {"performance", "none"} else asset
                if resolution.get("variant_kind") == "none":
                    target = asset
                default_variant = project.get("note_asset_entity_variants", {}).get(key)
                if (
                    default_variant
                    and not variant
                    and variant_kind != "performance"
                    and resolution.get("variant_kind") not in {"performance", "none"}
                ):
                    target = next(
                        (v for v in asset.get("derivatives", {}).values() if v.get("asset_id") == default_variant), None
                    )
                    if target is None:
                        continue
                if (
                    variant
                    and variant_kind == "unclassified"
                    and digest([key, variant]) not in variants
                    and variant not in asset.get("derivatives", {})
                ):
                    issues[mention["id"]] = {"code": "variant_classification", "candidates": [], "blocking": blocking}
                    variant = ""
                if variant:
                    try:
                        validate_asset_name(variant)
                    except ValueError:
                        issues[mention["id"]] = {"code": "variant_invalid", "candidates": [], "blocking": blocking}
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
                if context != "unclassified" and variant_kind != "performance":
                    active_visuals[visual_scope] = target
                first = {"id": note["id"], "order": note["order"], "title": note["title"]}
                keep_first_note(asset, first)
                keep_first_note(target, first)
                links[mention["id"]] = {
                    "asset_id": target["asset_id"],
                    "entity_id": asset["entity_id"],
                    "asset_code": target["asset_code"],
                    "note_id": note["id"],
                    "performance": performance,
                    "state": state,
                    "appearance_context": context,
                    "variant_kind": variant_kind,
                }
                review = project.get("note_asset_identity_reviews", {}).get(mention["id"])
                if review:
                    issues[mention["id"]] = {
                        "code": "identity_ambiguous",
                        "candidates": review["candidates"],
                        "blocking": False,
                        "reason": review["reason"],
                    }
        store.write(path / "project.json", project)
        return {"registered": registered, "linked": len(links)}


def reference(project: dict, mention: dict) -> dict:
    link = project.get("note_asset_links", {}).get(mention["id"])
    issue = project.get("note_asset_issues", {}).get(mention["id"])
    problem = (
        {
            "asset_issue": issue["code"],
            "identity_candidates": issue["candidates"],
            "asset_issue_blocking": issue.get("blocking", True),
            "asset_issue_reason": issue.get("reason", ""),
        }
        if issue
        else {}
    )
    if not link:
        return {**problem, "asset_missing": True} if issue else {}
    for bucket in BUCKETS.values():
        for name, asset in project.get(bucket, {}).items():
            if asset.get("asset_id") == link["asset_id"]:
                return {**link, **problem, "asset_name": name, "first_note": asset.get("first_note")}
            for variant, value in asset.get("derivatives", {}).items():
                if value.get("asset_id") == link["asset_id"]:
                    return {
                        **link,
                        **problem,
                        "asset_name": name,
                        "variant": variant,
                        "first_note": value.get("first_note"),
                    }
    return {**link, **problem, "asset_missing": True}


def annotate(project: dict, reading: dict | None) -> dict | None:
    if reading is None:
        return None
    result = deepcopy(reading)
    result["assets"] = [
        {
            **a,
            "source_variant": a.get("variant", ""),
            **reference(project, a),
            "variant": reference(project, a).get("variant", ""),
        }
        for a in reading.get("assets", [])
    ]
    return result


def resolve(
    path,
    project,
    mention_id,
    expected,
    reading_basis,
    entity_id,
    create_new,
    variant_kind,
    variant_name,
    appearance_context="current",
):
    """Explicit identity/variant decision; source readings remain immutable."""
    with project_metadata_lock(path):
        project = load_json(path / "project.json")
        notebook = store.require_current(path, project, expected)
        readings = store.valid_readings(path, notebook)
        found = next(((r, a) for r in readings.values() for a in r.get("assets", []) if a["id"] == mention_id), None)
        if not found or found[0]["basis"] != reading_basis:
            raise ValueError("资产依据已变化，请刷新后处理")
        mention = found[1]
        if not create_new and not any(
            a.get("asset_id") == entity_id for a in project.get(BUCKETS[mention["kind"]], {}).values()
        ):
            raise ValueError("请选择该类型已存在的本体资产，或明确另建资产")
        if variant_kind == "visual":
            if mention["kind"] == "character":
                variant_name = validate_asset_name(variant_name)
        elif variant_kind not in {"performance", "none"}:
            raise ValueError("请明确选择视觉变体、表现或无变体")
        live = load_json(path / "project.json")
        previous = deepcopy(live)
        live.setdefault("note_asset_identity_reviews", {}).pop(mention_id, None)
        live.setdefault("note_asset_resolutions", {})[mention_id] = {
            "entity_id": entity_id if not create_new else None,
            "create_new": create_new,
            "variant_kind": variant_kind,
            "variant_name": variant_name,
            "appearance_context": appearance_context,
        }
        store.write(
            store.root(path)
            / "history"
            / f"asset-resolution-{digest([mention_id, live['note_asset_resolutions'][mention_id]])}.json",
            previous,
        )
        store.write(path / "project.json", live)
    return synchronize(path)
