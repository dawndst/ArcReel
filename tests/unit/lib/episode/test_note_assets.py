"""Permanent asset identity must survive changing evidence and native edits."""

from copy import deepcopy

from lib.infra.json_io import load_json
from lib.novel_workflow import assets, store
from lib.project.asset_codes import ensure_asset_codes
from tests.unit.lib.episode.test_novel_workflow import project


def mention(note, record="m1", name="景麒", scope="", variant=""):
    return {
        "id": record,
        "kind": "character",
        "name": name,
        "identity_scope": scope,
        "description": "本章的人物外观",
        "variant": variant,
        "variant_kind": "visual" if variant else "none",
        "evidence": {"note_id": note["id"], "quote": "原文依据"},
    }


def save_reading(path, note, records):
    store.write(
        store.root(path) / "notes" / note["id"] / f"{store.reading_key(path, note)}.json",
        {"basis": note["basis"], "assets": records},
    )


def test_reread_and_rename_preserve_code(tmp_path):
    _, book = project(tmp_path)
    note = book["notes"][0]
    a = mention(note)
    save_reading(tmp_path, note, [a])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    old = assets.reference(data, a)
    data["characters"]["景麒新名"] = data["characters"].pop("景麒")
    store.write(tmp_path / "project.json", data)
    b = {**a, "id": "new-evidence", "description": "不同表述"}
    save_reading(tmp_path, note, [b])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    new = assets.reference(data, b)
    assert old["asset_code"] == new["asset_code"] == "CHR-001"
    assert new["asset_name"] == "景麒新名"
    assert len(data["characters"]) == 1
    assert data["characters"]["景麒新名"]["description"] == a["description"]


def test_variants_scopes_and_deletion(tmp_path):
    _, book = project(tmp_path)
    note = book["notes"][0]
    a, b, c = mention(note), mention(note, "beast", variant="兽形"), mention(note, "other", scope="另一个同名人物")
    save_reading(tmp_path, note, [a, b, c])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert assets.reference(data, c)["asset_issue"] == "identity_ambiguous"
    assets.resolve(tmp_path, data, c["id"], book["source_basis"], note["basis"], "", True, "none", "")
    data = load_json(tmp_path / "project.json")
    refs = [assets.reference(data, item) for item in [a, b, c]]
    assert len({r["asset_code"] for r in refs}) == 3
    assert refs[0]["entity_id"] == refs[1]["entity_id"] != refs[2]["entity_id"]
    assert refs[1]["variant"] == "兽形"
    del data["characters"]["景麒"]
    store.write(tmp_path / "project.json", data)
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert assets.reference(data, a)["asset_missing"] is True
    assert "景麒" not in data["characters"]
    data["characters"]["新人物"] = {"description": ""}
    ensure_asset_codes(data)
    assert data["characters"]["新人物"]["asset_code"] == "CHR-004"


def test_cross_note_identity_and_no_future_description(tmp_path):
    _, book = project(tmp_path)
    first, later = book["notes"]
    a, b = mention(first), mention(later, "later")
    b["description"] = "后文才揭示的身份"
    for note, item in [(first, a), (later, b)]:
        save_reading(tmp_path, note, [item])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert assets.reference(data, a)["asset_code"] == assets.reference(data, b)["asset_code"]
    original = {"assets": [a]}
    old = deepcopy(original)
    annotated = assets.annotate(data, original)
    assert original == old
    assert annotated["assets"][0]["description"] == "本章的人物外观"
    assert data["characters"]["景麒"]["description"] == "本章的人物外观"


def test_native_asset_and_generic_identity(tmp_path):
    data, book = project(tmp_path)
    data["characters"] = {"景麒": {"description": "人工设定"}}
    store.write(tmp_path / "project.json", data)
    for index, note in enumerate(book["notes"]):
        save_reading(tmp_path, note, [mention(note, f"hero{index}"), mention(note, f"generic{index}", name="士兵")])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert len(data["characters"]) == 3
    assert data["characters"]["景麒"]["description"] == "人工设定"


def test_variant_rename_and_removal_do_not_recreate_it(tmp_path):
    _, book = project(tmp_path)
    note = book["notes"][0]
    a = mention(note, variant="兽形")
    save_reading(tmp_path, note, [a])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    table = data["characters"]["景麒"]["derivatives"]
    table["麒麟形态"] = table.pop("兽形")
    store.write(tmp_path / "project.json", data)
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert assets.reference(data, a)["variant"] == "麒麟形态"
    assert len(data["characters"]["景麒"]["derivatives"]) == 1
    data["characters"]["景麒"]["derivatives"] = {}
    store.write(tmp_path / "project.json", data)
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert assets.reference(data, a)["asset_missing"]
    assert data["characters"]["景麒"]["derivatives"] == {}


def test_manual_merge_preserves_note_links_and_reread(tmp_path):
    from lib.project.asset_codes import merge_note_links
    from lib.project.asset_merge import plan_derivative_merge

    _, book = project(tmp_path)
    note = book["notes"][0]
    a, b = mention(note), mention(note, "masked", name="神秘来客")
    save_reading(tmp_path, note, [a, b])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    kept = data["characters"]["景麒"]
    discarded = data["characters"].pop("神秘来客")
    original_code = discarded["asset_code"]
    plan = plan_derivative_merge(discarded, kept, "神秘来客", as_derivative=True)
    kept["derivatives"] = {plan.created: {"description": "伪装"}}
    merge_note_links(data, discarded, kept, plan)
    store.write(tmp_path / "project.json", data)
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    ref = assets.reference(data, b)
    assert ref["asset_name"] == "景麒"
    assert ref["variant"] == "神秘来客"
    assert ref["asset_code"] == original_code
    assert len(data["characters"]) == 1


def test_first_appearance_uses_source_order_and_tracks_variant_separately(tmp_path):
    _, book = project(tmp_path)
    first, later = book["notes"]
    save_reading(tmp_path, later, [mention(later, "later", variant="兽形")])
    assets.synchronize(tmp_path)
    saved = load_json(tmp_path / "project.json")["characters"]["景麒"]
    assert saved["first_note"]["id"] == later["id"]
    save_reading(tmp_path, first, [mention(first, "first")])
    # Later reading is keyed by its preceding context; resave after adding the earlier Note.
    save_reading(tmp_path, later, [mention(later, "later", variant="兽形")])
    assets.synchronize(tmp_path)
    saved = load_json(tmp_path / "project.json")["characters"]["景麒"]
    assert saved["first_note"] == {"id": first["id"], "order": first["order"], "title": first["title"]}
    assert saved["derivatives"]["兽形"]["first_note"]["id"] == later["id"]


def test_identity_anchor_ignores_descriptive_scope_changes(tmp_path):
    _, book = project(tmp_path)
    note = book["notes"][0]
    a = mention(note, scope="怪物")
    b = {**mention(note, "m2", scope="未知妖魔"), "same_entity_as": a["id"]}
    save_reading(tmp_path, note, [a, b])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert len(data["characters"]) == 1
    assert assets.reference(data, a)["entity_id"] == assets.reference(data, b)["entity_id"]


def test_sound_is_not_visual_and_invalid_variant_is_not_silently_lost(tmp_path):
    _, book = project(tmp_path)
    note = book["notes"][0]
    a = {**mention(note, variant="幻听/笑声"), "variant_kind": "performance"}
    save_reading(tmp_path, note, [a])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert not data["characters"]["景麒"].get("derivatives")
    assert assets.reference(data, a)["performance"] == "幻听/笑声"
    b = {**a, "id": "invalid", "variant_kind": "visual"}
    save_reading(tmp_path, note, [b])
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert assets.reference(data, b)["asset_issue"] == "variant_invalid"
    assets.resolve(
        tmp_path,
        data,
        b["id"],
        book["source_basis"],
        note["basis"],
        data["characters"]["景麒"]["asset_id"],
        False,
        "performance",
        "只闻笑声",
    )
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    assert not assets.reference(data, b).get("asset_issue")
    assert assets.reference(data, b)["performance"] == "只闻笑声"
    assert len(data["characters"]) == 1


def test_new_unclassified_variant_stays_pending_until_explicit_resolution(tmp_path):
    _, book = project(tmp_path)
    note = book["notes"][0]
    a = {**mention(note, variant="言语诱惑"), "variant_kind": "unclassified"}
    save_reading(tmp_path, note, [a])
    assets.synchronize(tmp_path)
    assets.synchronize(tmp_path)
    data = load_json(tmp_path / "project.json")
    ref = assets.reference(data, a)
    assert ref["asset_issue"] == "variant_classification"
    assert ref["asset_issue_blocking"] is True
    assert not data["characters"]["景麒"].get("derivatives")
