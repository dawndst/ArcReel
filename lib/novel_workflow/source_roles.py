"""Register source-backed speaking roles omitted by the original Note extraction."""

from lib.novel_understanding.store import digest
from lib.project.asset_codes import ensure_asset_codes, keep_first_note
from lib.project.asset_types import asset_name_comparison_key, validate_asset_name


def register(project, note, reading_basis, label, evidence):
    label = validate_asset_name(label)
    # A role label is local to one original chapter; generic labels never unify unrelated chapters.
    key = digest([note["id"], label])
    roles = project.setdefault("note_source_roles", {})
    previous = roles.get(key)
    bucket = project.setdefault("characters", {})
    found = next(((n, a) for n, a in bucket.items() if previous and a.get("asset_id") == previous["entity_id"]), None)
    if previous and not found:
        raise ValueError("该角色资产已移除，请先恢复或明确处理原有关联")
    if found:
        name, asset = found
    else:
        original = label if label.endswith("（未具名）") else label + "（未具名）"
        name, suffix = original, 1
        occupied = {
            asset_name_comparison_key(n)
            for b in ("characters", "scenes", "props", "products")
            for n in project.get(b, {})
        }
        while asset_name_comparison_key(name) in occupied:
            suffix += 1
            name = f"{original}（{suffix}）"
        bucket[name] = asset = {
            "description": f"原文角色标签：{label}。原文未给姓名；只按引用中的行为与身份制作，未交代的年龄、发色、服装细节不得编造。",
            "note_managed": True,
            "note_source_names": [label],
            "identity_level": "individual",
        }
        ensure_asset_codes(project)
    first = {"id": note["id"], "order": note["order"], "title": note["title"]}
    keep_first_note(asset, first)
    if previous and previous["reading_basis"] == reading_basis and previous["evidence"]["start"] <= evidence["start"]:
        evidence = previous["evidence"]
    record = {
        "id": previous["id"] if previous else "source-role-" + key[:24],
        "kind": "character",
        "claim_type": "fact",
        "source_kind": "narrative",
        "name": label,
        "identity_scope": f"Note {note['order']:03d} · {label}",
        "description": f"{label}；原文未给姓名。仅按本段行为与身份登记，未明确的外貌继续留空。",
        "variant": "",
        "reading_basis": reading_basis,
        "evidence": evidence,
        "entity_id": asset["asset_id"],
    }
    roles[key] = record
    from lib.novel_workflow.assets import entity_key

    project.setdefault("note_asset_entities", {})[entity_key(record, note["id"])] = asset["asset_id"]
    project.setdefault("note_asset_links", {})[record["id"]] = {
        "asset_id": asset["asset_id"],
        "entity_id": asset["asset_id"],
        "asset_code": asset["asset_code"],
        "note_id": note["id"],
        "variant_kind": "none",
        "appearance_context": "current",
    }
    return name
