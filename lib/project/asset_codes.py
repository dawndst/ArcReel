"""Project-local permanent production asset numbers, including character derivatives."""

from uuid import uuid4

from lib.project.asset_types import asset_name_comparison_key

BUCKETS = {"characters": "CHR", "scenes": "LOC", "props": "PRP", "products": "AST"}


def ensure_asset_codes(project: dict) -> None:
    counters = project.setdefault("asset_code_counters", {})
    entries = []
    for bucket, prefix in BUCKETS.items():
        for asset in project.get(bucket, {}).values():
            entries.append((prefix, asset, None))
            entries.extend((prefix, variant, asset) for variant in asset.get("derivatives", {}).values())
    # Retain high-water marks even after deletion; never recycle numbers.
    for prefix, asset, _ in entries:
        code = asset.get("asset_code", "")
        if code.startswith(prefix + "-") and code[len(prefix) + 1 :].isdigit():
            counters[prefix] = max(counters.get(prefix, 0), int(code[len(prefix) + 1 :]))
    for prefix, asset, parent in entries:
        if not asset.get("asset_code"):
            counters[prefix] = counters.get(prefix, 0) + 1
            asset["asset_code"] = f"{prefix}-{counters[prefix]:03d}"
        asset.setdefault("asset_id", uuid4().hex)
        asset["entity_id"] = parent["entity_id"] if parent else asset.get("entity_id", asset["asset_id"])


def keep_first_note(asset: dict, first: dict | None) -> None:
    if first and (not asset.get("first_note") or first["order"] < asset["first_note"]["order"]):
        asset["first_note"] = dict(first)


def merge_note_links(project: dict, discarded: dict, kept: dict, plan) -> None:
    """Carry Note references through the creator's native asset merge operation."""
    ensure_asset_codes(project)
    table = {asset_name_comparison_key(n): a for n, a in kept.get("derivatives", {}).items()}
    target = table[plan.source_derivative] if plan.source_derivative else kept
    if plan.created and discarded.get("asset_id"):
        for field in ("asset_id", "asset_code"):
            target[field] = discarded[field]
    old_id = discarded.get("asset_id")
    for key, value in project.get("note_asset_entities", {}).items():
        if value == old_id:
            project["note_asset_entities"][key] = kept["asset_id"]
            if plan.source_derivative:
                project.setdefault("note_asset_entity_variants", {})[key] = target["asset_id"]
    keep_first_note(target, discarded.get("first_note"))
    keep_first_note(kept, discarded.get("first_note"))
    replacements = {old_id: target}
    for name, old in discarded.get("derivatives", {}).items():
        resolved = plan.derivative_names.get(asset_name_comparison_key(name))
        if resolved in table:
            keep_first_note(table[resolved], old.get("first_note"))
            replacements[old.get("asset_id")] = table[resolved]
    for key, value in project.get("note_asset_variants", {}).items():
        if value in replacements:
            project["note_asset_variants"][key] = replacements[value]["asset_id"]
    for key, value in project.get("note_asset_entity_variants", {}).items():
        if value in replacements:
            project["note_asset_entity_variants"][key] = replacements[value]["asset_id"]
    for resolution in project.get("note_asset_resolutions", {}).values():
        if resolution.get("entity_id") != old_id:
            continue
        resolution["entity_id"] = kept["asset_id"]
        resolution["create_new"] = False
        if resolution.get("variant_kind") == "visual":
            old_variant = asset_name_comparison_key(resolution.get("variant_name", ""))
            resolved = plan.derivative_names.get(old_variant)
            if resolved in table:
                resolution["variant_name"] = next(n for n, a in kept["derivatives"].items() if a is table[resolved])
        elif plan.source_derivative:
            resolution.update(
                variant_kind="visual",
                variant_name=next(n for n, a in kept["derivatives"].items() if a is target),
            )
    kept["note_source_names"] = list(
        dict.fromkeys([*kept.get("note_source_names", []), *discarded.get("note_source_names", [])])
    )
    kept_name = next(n for bucket in BUCKETS for n, a in project.get(bucket, {}).items() if a is kept)
    for issue in [
        *project.get("note_asset_issues", {}).values(),
        *project.get("note_asset_identity_reviews", {}).values(),
    ]:
        candidates = []
        for candidate in issue.get("candidates", []):
            if candidate.get("entity_id") == old_id:
                candidate = {"entity_id": kept["asset_id"], "name": kept_name, "asset_code": kept["asset_code"]}
            if candidate not in candidates:
                candidates.append(candidate)
        issue["candidates"] = candidates
    for link in project.get("note_asset_links", {}).values():
        if link.get("asset_id") in replacements:
            asset = replacements[link["asset_id"]]
            link.update(asset_id=asset["asset_id"], asset_code=asset["asset_code"], entity_id=kept["entity_id"])
