from lib.episode.episode_guide import cached, save, snapshot
from lib.episode.episode_guide_models import EpisodeGuide
from lib.episode.episode_planner import DramaEpisodeDraft, _candidate_entry_from_draft


def test_guide_uses_only_current_slice_and_invalidates_after_changes(tmp_path):
    (tmp_path / "source").mkdir()
    source = tmp_path / "source" / "book.txt"
    source.write_text("本集秘密后文真相", encoding="utf-8")
    project = {
        "whole_source_files": [{"source_file": "source/book.txt"}],
        "episodes": [{"episode": 1, "source_range": {"source_file": "source/book.txt", "start": 0, "end": 4}}],
    }
    data = snapshot(tmp_path, project, 1)
    assert data["text"] == "本集秘密"
    guide = EpisodeGuide(
        summary="因果概况",
        story_beats=["遭遇冲突"],
        character_changes=["关系改变"],
        adaptation_value="推进主线",
        recommendation="keep",
        recommendation_reason="冲突未解决",
        ending_hook="秘密未解",
    )
    save(tmp_path, data, guide)
    assert cached(tmp_path, snapshot(tmp_path, project, 1))["guide"]["summary"] == "因果概况"
    source.write_text("本集改变后文真相", encoding="utf-8")
    result = cached(tmp_path, snapshot(tmp_path, project, 1))
    assert result["stale"] is True
    assert result["guide"] is None
    (tmp_path / "episode_guides" / "guide.md").write_text("项目独立规则", encoding="utf-8")
    assert snapshot(tmp_path, project, 1)["rule"] == "项目独立规则"


def test_planner_preserves_complete_guide_in_candidate():
    data = {
        "summary": "完整概况",
        "story_beats": ["应对阻力"],
        "character_changes": ["信任破裂"],
        "adaptation_value": "人物转折",
        "recommendation": "compress",
        "recommendation_reason": "保留转折",
        "ending_hook": "去向未知",
    }
    draft = DramaEpisodeDraft(title="转折", hook="未知", end_anchor="结束", story_beats=["应对"], guide=data)
    result = _candidate_entry_from_draft(draft, source_rel="source/book.txt", start=0, end=100)
    assert result["outline"]["guide"] == data
