import asyncio

import pytest

from lib.novel_workflow import retrieval, scope, store
from lib.novel_workflow.service import generate_svts, read_notes
from tests.unit.lib.episode.test_novel_workflow import Reader, SVTReader, project


async def test_partial_reading_can_produce_svts_and_later_extend(tmp_path):
    data, notebook = await asyncio.to_thread(project, tmp_path)
    first, second = [n["id"] for n in notebook["notes"]]
    expected = notebook["source_basis"]
    await read_notes(tmp_path, Reader(), [first], expected)
    assert scope.available_ids(tmp_path, notebook) == {first}
    await generate_svts(tmp_path, SVTReader(), [first], expected)
    assert len(store.view(tmp_path, data)["svts"]) == 1
    await read_notes(tmp_path, Reader(), [second], expected)
    assert scope.available_ids(tmp_path, notebook) == {first, second}
    assert set(store.valid_readings(tmp_path)) == {first, second}
    scope.configure(tmp_path, data, [first], expected)
    assert set(store.valid_readings(tmp_path)) == {first}
    with pytest.raises(ValueError, match="可用范围"):
        scope.require(tmp_path, notebook, [second])


def test_scope_separates_retrieval_cache_and_rejects_invalid_selection(tmp_path):
    data, notebook = project(tmp_path)
    first, second = [n["id"] for n in notebook["notes"]]
    assert retrieval.search(retrieval.index(tmp_path, data, notebook), ["城门"])
    scope.configure(tmp_path, data, [first], notebook["source_basis"])
    assert not retrieval.search(retrieval.index(tmp_path, data, notebook), ["城门"])
    for invalid in [[], ["missing"], [first, first]]:
        with pytest.raises(ValueError, match="有效章节"):
            scope.configure(tmp_path, data, invalid, notebook["source_basis"])
        assert scope.available_ids(tmp_path, notebook) == {first}
    scope.configure(tmp_path, data, [second], notebook["source_basis"], extend=True)
    assert retrieval.search(retrieval.index(tmp_path, data, notebook), ["城门"])
