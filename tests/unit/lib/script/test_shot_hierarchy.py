"""Scene/shot parentage survives plan → production, with a hard segment limit."""

import pytest
from pydantic import ValidationError

from lib.prompts.prompt_builders_script import render_drama_content_for_prompt_authoring
from lib.script.script_models import DramaEpisodeScript, DramaNormalizedScript, build_drama_normalized_script_model


def unit(index=1, **patch):
    return {
        "scene_id": f"E1S{index:02d}",
        "scene_number": 1,
        "shot_number": 1,
        "segment_number": None,
        "duration_seconds": 12,
        "characters_in_scene": [],
        "scene_description": "人物走向门口",
        "utterances": [],
        "source_text": "原文",
        **patch,
    }


def test_24_second_shot_is_two_segments_and_survives_materialization():
    scenes = [unit(segment_number=1), unit(2, segment_number=2, scene_description="人物接着打开门")]
    plan = build_drama_normalized_script_model([8, 12, 20], hierarchy=True).model_validate(
        {"title": "本集", "scenes": scenes}
    )
    script = DramaEpisodeScript.model_validate(
        {
            "title": "本集",
            "scenes": [
                {**s.model_dump(), "image_prompt": None, "video_prompt": None, "pending_authoring": True}
                for s in plan.scenes
            ],
        }
    )
    assert sum(s.duration_seconds for s in script.scenes) == 24
    assert [s.segment_number for s in script.scenes] == [1, 2]
    assert {s.shot_number for s in script.scenes} == {1}
    assert [s.scene_description for s in script.scenes] == ["人物走向门口", "人物接着打开门"]


@pytest.mark.parametrize("duration", [16, 20, 60])
def test_segment_duration_is_hard_limited_even_in_formal_scripts(duration):
    with pytest.raises(ValidationError, match="15"):
        DramaNormalizedScript.model_validate({"title": "本集", "scenes": [unit(duration_seconds=duration)]})


def test_fifteen_seconds_does_not_need_segments():
    plan = build_drama_normalized_script_model([15, 30], hierarchy=True)
    result = plan.model_validate({"title": "本集", "scenes": [unit(duration_seconds=15)]})
    assert result.scenes[0].segment_number is None
    with pytest.raises(ValueError, match="15秒"):
        build_drama_normalized_script_model([20, 30], hierarchy=True)


@pytest.mark.parametrize(
    "scenes",
    [
        [unit(), unit(2)],
        [unit(segment_number=1), unit(2, segment_number=3)],
        [unit(segment_number=1), unit(2, shot_number=2), unit(3, segment_number=2)],
        [unit(), unit(2, scene_number=None, shot_number=None)],
    ],
)
def test_invalid_parentage_rejected(scenes):
    with pytest.raises(ValidationError):
        DramaNormalizedScript.model_validate({"title": "本集", "scenes": scenes})


def test_generation_requires_explicit_scene_and_shot_numbers():
    scene = unit()
    del scene["scene_number"]
    del scene["shot_number"]
    with pytest.raises(ValidationError):
        build_drama_normalized_script_model([12], hierarchy=True).model_validate({"title": "本集", "scenes": [scene]})


def test_visual_prompt_preserves_seg_continuity():
    text = render_drama_content_for_prompt_authoring([unit(segment_number=1), unit(2, segment_number=2)])
    assert "SCN1 / SH1 / SEG2" in text
    assert "连续" in text


def test_scene_groups_use_narrative_scene_not_seg_break():
    from lib.script.storyboard_sequence import group_scenes_by_segment_break

    scenes = [unit(segment_number=1), unit(2, segment_number=2, segment_break=True), unit(3, scene_number=2)]
    groups = group_scenes_by_segment_break(scenes, "scene_id")
    assert [len(group) for group in groups] == [2, 1]


def test_new_shot_and_deleted_segment_preserve_logical_parentage():
    from lib.script.script_batch_edit import blank_item_after
    from lib.script.shot_hierarchy import repair_removed_segments

    original = {"content_mode": "drama", "scenes": [unit(segment_number=1), unit(2, segment_number=2)]}
    added = blank_item_after(original, "E1S01")
    assert (added["scene_number"], added["shot_number"], added["segment_number"]) == (1, 2, None)
    candidate = {"scenes": [dict(original["scenes"][1])]}
    repair_removed_segments(original, candidate)
    assert candidate["scenes"][0]["segment_number"] is None
    assert candidate["scenes"][0]["scene_id"] == "E1S02"


def test_first_manual_shot_starts_the_hierarchy():
    from lib.script.script_batch_edit import blank_item_after

    item = blank_item_after({"content_mode": "drama", "scenes": []}, None)
    assert (item["scene_number"], item["shot_number"], item["segment_number"]) == (1, 1, None)
    assert item["duration_seconds"] <= 15
