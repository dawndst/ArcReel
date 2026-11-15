"""Register source-backed assets omitted by the original Note extraction."""

from lib.novel_workflow.common import digest
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


def register_existing_asset(project, note, reading_basis, kind, entity_id, evidence, source_text):
    """Supplement an omitted physical appearance without changing the Note's claims.

    Callers must verify the identity; only a literal source span attributed to this Note is accepted.
    No new asset or ownership/identity claim is inferred here.
    """
    from lib.novel_workflow.assets import BUCKETS, entity_key

    if kind not in BUCKETS or evidence.get("note_id") != note["id"]:
        raise ValueError("资产类型或原文 Note 不匹配")
    start, end = evidence["start"], evidence["end"]
    if not (0 <= start < end <= len(source_text)) or source_text[start:end] != evidence["quote"]:
        raise ValueError("补充资产必须提供准确的连续原文")
    found = next(
        ((name, asset) for name, asset in project.get(BUCKETS[kind], {}).items() if asset.get("asset_id") == entity_id),
        None,
    )
    if not found:
        raise ValueError("关联资产不存在")
    name, asset = found
    key = digest([note["id"], kind, entity_id, "source-appearance"])
    record = {
        "id": "source-asset-" + key[:24],
        "kind": kind,
        "claim_type": "fact",
        "source_kind": "narrative",
        "name": name,
        "identity_scope": f"Note {note['order']:03d} · {name}",
        "description": "原文补充出场依据：" + evidence["quote"],
        "variant": "",
        "reading_basis": reading_basis,
        "evidence": evidence,
        "entity_id": entity_id,
    }
    project.setdefault("note_source_roles", {})[key] = record
    project.setdefault("note_asset_entities", {})[entity_key(record, note["id"])] = entity_id
    project.setdefault("note_asset_links", {})[record["id"]] = {
        "asset_id": entity_id,
        "entity_id": entity_id,
        "asset_code": asset["asset_code"],
        "note_id": note["id"],
        "variant_kind": "none",
        "appearance_context": "current",
    }
    keep_first_note(asset, {"id": note["id"], "order": note["order"], "title": note["title"]})
    return name
