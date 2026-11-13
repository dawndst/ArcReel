import asyncio
import json
from types import SimpleNamespace

import pytest

from lib.infra.json_io import load_json
from lib.novel_workflow import question_register as registry
from lib.novel_workflow import store, understanding
from tests.unit.lib.episode.test_cross_chapter_understanding import CrossReader, setup


async def report_fixture(path, questions=None):
    _, book = await asyncio.to_thread(setup, path)
    first, second = book["notes"][:2]
    await understanding.understand_notes(path, CrossReader(), [first["id"]], book["source_basis"])
    report_file = next((store.root(path) / "understanding/reports").glob("*.json"))
    report = await asyncio.to_thread(load_json, report_file)
    report["unresolved"] = questions or [
        {"note_id": first["id"], "question": "景麒为什么称阳子为主人？"},
        {"note_id": second["id"], "question": "景麒所说的主从关系有何制度依据？"},
        {"note_id": first["id"], "question": "这句对白的说话人是否误判？"},
    ]
    await asyncio.to_thread(store.write, report_file, report)
    return book, report, report_file


def material(request):
    return json.loads(request.prompt.split("问题归并材料：", 1)[1].split("\n只输出 JSON", 1)[0])


class Grouper:
    def __init__(self):
        self.calls = 0

    async def generate(self, request, **kwargs):
        self.calls += 1
        data = material(request)
        assert len(data["questions"]) == 3
        return SimpleNamespace(
            text=json.dumps(
                {
                    "groups": [
                        {
                            "title": "景麒称阳子为主人的依据",
                            "kind": "plot_unrevealed",
                            "explanation": "身份制度仍是剧情追踪项",
                            "source_ids": [0, 1],
                            "evidence_ids": [0] if data["existing_evidence"] else [],
                        },
                        {
                            "title": "对白说话人需核对",
                            "kind": "extraction_check",
                            "explanation": "对照上下文确认归属",
                            "source_ids": [2],
                            "evidence_ids": [],
                        },
                    ]
                }
            )
        )


async def test_grouping_preserves_every_original_and_evidence_without_rewriting_facts(tmp_path):
    book, report, report_file = await report_fixture(tmp_path)
    before = await asyncio.to_thread(report_file.read_bytes)
    production = await asyncio.to_thread(
        understanding.production_context, tmp_path, [book["notes"][1]["id"]], source_offset=99999
    )
    generator = Grouper()
    result = await registry.build(tmp_path, generator, report, book)
    assert result["original_count"] == 3
    assert result["group_count"] == 2
    assert result["counts"] == {"plot_unrevealed": 1, "extraction_check": 1}
    assert {i for g in result["groups"] for i in g["original_ids"]} == {o["id"] for o in result["originals"]}
    assert result["groups"][0]["note_ids"] == [book["notes"][0]["id"], book["notes"][1]["id"]]
    assert result["groups"][0]["link_ids"] == [report["links"][0]["id"]]
    assert await asyncio.to_thread(report_file.read_bytes) == before
    assert (
        await asyncio.to_thread(
            understanding.production_context, tmp_path, [book["notes"][1]["id"]], source_offset=99999
        )
        == production
    )
    cached = await registry.build(tmp_path, generator, report, book)
    assert cached["basis"] == result["basis"]
    assert generator.calls == 1
    viewed = await asyncio.to_thread(understanding.view, tmp_path)
    assert viewed["reports"][0]["question_register"]["group_count"] == 2
    assert not viewed["reports"][0]["stale"]


@pytest.mark.parametrize(
    "groups",
    [
        [{"title": "a", "kind": "extraction_check", "explanation": "核对", "source_ids": [0]}],
        [{"title": "a", "kind": "extraction_check", "explanation": "核对", "source_ids": [0, 0]}],
        [{"title": "a", "kind": "plot_unrevealed", "explanation": "追踪", "source_ids": [0, 1], "evidence_ids": [999]}],
    ],
)
def test_grouping_rejects_missing_duplicate_sources_and_invented_evidence(groups):
    cards = [
        {"original_ids": ["a"], "note_ids": ["n1"], "link_ids": []},
        {"original_ids": ["b"], "note_ids": ["n2"], "link_ids": []},
    ]
    with pytest.raises(ValueError, match=r"来源|编号|证据"):
        registry.regroup(registry.Grouping(groups=groups), cards, [])


async def test_rule_update_invalidates_register_without_invalidating_reading_or_cross_report(tmp_path):
    book, report, _ = await report_fixture(tmp_path)
    generator = Grouper()
    await registry.build(tmp_path, generator, report, book)
    await asyncio.to_thread((store.root(tmp_path) / "rules/understand_questions.md").write_text, "新的问题归并规则")
    current = await asyncio.to_thread(understanding.view, tmp_path)
    assert not current["reports"][0]["stale"]
    assert current["reports"][0]["question_register"]["stale"]
    await registry.build(tmp_path, generator, report, book)
    assert generator.calls == 2
    assert not (await asyncio.to_thread(registry.load, tmp_path, report))["stale"]


async def test_source_change_during_model_call_keeps_cache_without_publishing_stale_register(tmp_path):
    book, report, report_file = await report_fixture(tmp_path)
    base = Grouper()

    class ChangingGenerator:
        async def generate(self, request, **kwargs):
            response = await base.generate(request, **kwargs)
            await asyncio.to_thread(store.write, report_file, {**report, "source_basis": "changed"})
            return response

    with pytest.raises(ValueError, match=r"来源|范围|规则"):
        await registry.build(tmp_path, ChangingGenerator(), report, book)
    previous = await asyncio.to_thread(registry.load, tmp_path, report)
    assert previous is None or previous["stale"]
    assert (
        len(
            await asyncio.to_thread(
                lambda: list((store.root(tmp_path) / "understanding/question_groups").glob("*.json"))
            )
        )
        == 1
    )
