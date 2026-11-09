from lib.novel_workflow.chapters import index, chunks


def test_combines_parts_but_preserves_same_number_in_different_volumes(tmp_path):
    (tmp_path / "source").mkdir()
    text = "# 书名\n版权\n# 卷一\n# 第一章(上)\n人物甲\n# 第一章(中)\n人物乙\n# 第一章(下)\n人物丙\n# 第二章\n结束\n# 卷二\n# 第一章\n新的故事\n"
    (tmp_path / "source/book.txt").write_text(text)
    project = {"whole_source_files": [{"source_file": "source/book.txt"}]}
    result = index(tmp_path, project)
    assert len(result["notes"]) == 3
    assert len(result["notes"][0]["sections"]) == 3
    assert result["notes"][0]["id"] != result["notes"][2]["id"]
    pieces = chunks(tmp_path, project, result["notes"][0])
    assert "".join(p["text"] for p in pieces) == text[text.index("# 第一章(上)") : text.index("# 第二章")]
