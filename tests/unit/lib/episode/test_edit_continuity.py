from lib.novel_workflow import continuity
from lib.novel_workflow.delivery_review import director_notes


def shot(name, start, end, scene="room"):
    return {
        "id": name,
        "scene_id": scene,
        "segments": [{"asset_states": [{"kind": "prop", "name": "剑", "start_holder": start, "end_holder": end}]}],
    }


def test_compares_actual_edit_order_and_keeps_each_boundary_independent():
    a, b, c = shot("a", "甲", "乙"), shot("b", "乙", "乙"), shot("c", "丙", "甲")
    result = continuity.boundaries([a, c, b])
    assert [(item["from_shot"], item["to_shot"]) for item in result] == [("a", "c"), ("c", "b")]
    issues = continuity.issues(result)
    assert len(issues) == 2
    assert len({continuity.decision_key(issue) for issue in issues}) == 2
    assert not any(issue["hard"] for issue in issues)
    assert continuity.boundaries([a, b])[0]["status"] == "recorded"


def test_cross_scene_is_not_a_false_mismatch_and_missing_is_not_unchanged():
    assert continuity.boundaries([shot("a", "甲", "乙"), shot("b", "丙", "丁", "road")])[0]["status"] == "scene_change"
    boundary = continuity.boundaries([shot("a", "甲", "乙"), shot("b", "", "丁")])[0]
    assert boundary["states"][0]["status"] == "missing"
    split = shot("a", "甲", "乙")
    split["segments"].extend(shot("b", "乙", "丙")["segments"])
    assert continuity.boundaries([split])[0]["status"] == "recorded"


def test_native_production_receives_only_current_linked_adaptation_decisions():
    review = {
        "issues": [],
        "adaptation_decisions": [
            {
                "shot_ids": ["a"],
                "title": "取剑",
                "adaptation_action": "compress",
                "tradeoff": "保留行动因果，压缩重复对白",
            },
            {"shot_ids": ["b"], "title": "未选镜头"},
            {"shot_ids": ["a"], "title": "过期决定", "stale": True},
        ],
    }
    result = director_notes(review, "a", 0)
    assert "压缩重复对白" in result
    assert "未选镜头" not in result
    assert "过期决定" not in result
