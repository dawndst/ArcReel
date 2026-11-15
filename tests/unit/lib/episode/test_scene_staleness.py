from lib.novel_workflow import scene_library
from lib.novel_workflow.common import digest


def test_explains_all_invalid_dependencies_without_accepting_historical_shots(monkeypatch):
    monkeypatch.setattr(scene_library.store, "effective_rule", lambda *args: "new rule")
    monkeypatch.setattr(scene_library.understanding, "require_understood", lambda *args: None)
    monkeypatch.setattr(
        scene_library.understanding, "production_context", lambda *args, **kwargs: {"basis": "new understanding"}
    )
    batch = {
        "source_basis": "source",
        "rule_basis": digest("old rule"),
        "note_bases": {"n": "old note"},
        "note_id": "n",
        "svt_basis": "old svt",
        "understanding_basis": "old understanding",
    }
    book = {"source_basis": "source", "groups": []}
    assert scene_library.stale_reasons(None, batch, book, {}) == ["rules", "notes", "svt", "understanding"]
    assert not scene_library.valid_batch(None, batch, book, {})
    batch.update(rule_basis=digest("new rule"), understanding_basis="new understanding")
    batch.pop("svt_basis")
    assert scene_library.valid_batch(None, batch, book, {"n": {"basis": "old note"}})
