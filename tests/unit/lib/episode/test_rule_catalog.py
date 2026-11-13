from lib.novel_workflow import store
from lib.novel_workflow.rule_catalog import catalog
from tests.unit.lib.episode.test_novel_workflow import project


def test_catalog_reads_effective_project_rules_and_templates_without_mutation(tmp_path):
    data, _ = project(tmp_path)
    file = store.root(tmp_path) / "rules/svt.md"
    file.write_text("项目专属主归属规则")
    before = file.read_bytes()
    value = catalog(tmp_path, data)
    entries = {v["id"]: v for v in value["entries"]}
    assert value["read_only"] is True
    assert entries["novel/svt"]["content"] == store.effective_rule(tmp_path, "svt")
    assert entries["novel/svt"]["content"].startswith("项目专属主归属规则")
    assert entries["novel/svt"]["source"] == "project"
    assert "1200" in entries["novel/chapter"]["content"]
    assert any(k.startswith("template/") for k in entries)
    assert any(k.startswith("partial/") for k in entries)
    assert any(k.startswith("agent/") for k in entries)
    assert "agent/CLAUDE.drama.md" in entries
    assert file.read_bytes() == before
    assert not any(".env" in v["location"] for v in entries.values())


def test_catalog_reads_projected_current_mode_skill(tmp_path):
    data, _ = project(tmp_path)
    data["content_mode"] = "drama"
    skill = tmp_path / ".claude/skills/video-workflow/SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text("当前项目的 Note 工作流技能")
    entries = {e["id"]: e for e in catalog(tmp_path, data)["entries"]}
    current = entries["agent/.claude/skills/video-workflow/SKILL.drama.md"]
    assert current["content"] == "当前项目的 Note 工作流技能"
    assert current["source"] == "project"
    assert entries["agent/.claude/skills/video-workflow/SKILL.narration.md"]["category"] == "other"


def test_narrow_evidence_tools_use_selection_rules_without_production_instructions(tmp_path):
    data, _ = project(tmp_path)
    rules = store.effective_rule(tmp_path, "quote_locations")
    assert "原文候选选择的公共边界" in rules
    assert "场镜素材可以保留待确认对白" not in rules
    entries = {v["id"]: v for v in catalog(tmp_path, data)["entries"]}
    assert entries["novel/evidence_selection"]["content"] == store.effective_rule(tmp_path, "evidence_selection")
    assert entries["novel/scene_review"]["content"] == store.effective_rule(tmp_path, "scene_review")
