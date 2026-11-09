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
    assert entries["novel/svt"]["content"] == "项目专属主归属规则"
    assert entries["novel/svt"]["source"] == "project"
    assert "1200" in entries["novel/chapter"]["content"]
    assert any(k.startswith("template/") for k in entries)
    assert any(k.startswith("partial/") for k in entries)
    assert any(k.startswith("agent/") for k in entries)
    assert "agent/CLAUDE.drama.md" in entries
    assert file.read_bytes() == before
    assert not any(".env" in v["location"] for v in entries.values())
