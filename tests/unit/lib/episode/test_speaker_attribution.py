import pytest

from lib.novel_workflow.shot_production import planning_inputs
from lib.novel_workflow.speaker_attribution import Suggestions, validate


def data():
    return {
        "source": {"text": "阳子喊道：走吧。", "source_file": "book", "start": 100},
        "pending": [{"segment_index": 0, "utterance_index": 0, "text": "走吧"}],
        "candidates": [{"name": "阳子"}],
    }


def suggestion(speaker="阳子", quote="阳子喊道：走吧。"):
    return Suggestions.model_validate(
        {
            "items": [
                {
                    "segment_index": 0,
                    "utterance_index": 0,
                    "speaker": speaker,
                    "source_quote": quote,
                    "reason": "引语前有明确归属",
                }
            ]
        }
    )


def test_attribution_has_exact_source_coordinates_and_allows_uncertainty():
    value = validate(suggestion(), data())[0]
    assert value["evidence"] == {"source_file": "book", "start": 100, "end": 108, "quote": "阳子喊道：走吧。"}
    assert validate(suggestion(None, ""), data())[0]["speaker"] is None


@pytest.mark.parametrize(("speaker", "quote"), [("杉本", "阳子喊道：走吧。"), ("阳子", ""), ("阳子", "小说没有这一句")])
def test_unsupported_speaker_or_evidence_is_rejected(speaker, quote):
    with pytest.raises(ValueError, match=r"说话人|引文"):
        validate(suggestion(speaker, quote), data())


def test_missing_and_duplicate_items_are_rejected():
    with pytest.raises(ValueError, match="每条"):
        validate(Suggestions(items=[]), data())
    value = suggestion()
    value.items *= 2
    with pytest.raises(ValueError, match="每条"):
        validate(value, data())


def test_readonly_suggestions_do_not_invalidate_shot_design():
    shot = {"evidence": {}, "segments": []}
    before = planning_inputs({}, "rules", {"sh": shot}, {}, {"assets": []})[2]
    shot["speaker_suggestions"] = {"items": []}
    assert planning_inputs({}, "rules", {"sh": shot}, {}, {"assets": []})[2] == before


def test_missing_unnamed_role_is_a_grounded_proposal_not_an_existing_speaker():
    value = suggestion(None)
    value.items[0].proposed_role = "借课本的女同学"
    result = validate(value, data())[0]
    assert result["speaker"] is None
    assert result["proposed_role"] == "借课本的女同学"
    assert result["evidence"]["start"] == 100
    value.items[0].speaker = "阳子"
    with pytest.raises(ValueError, match="不能同时"):
        validate(value, data())
