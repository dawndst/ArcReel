from lib.novel_workflow.models import Reading, ReadingQuestion, Relation
from lib.novel_workflow.service import ground


def test_reading_question_categories_reach_existing_understanding_input():
    reading = Reading(
        complete=True,
        summary="摘要",
        questions=["旧疑问"],
        reading_questions=[
            ReadingQuestion(text="谁在追踪？", kind="plot_unrevealed"),
            ReadingQuestion(text="旧疑问", kind="extraction_check"),
        ],
    )
    result = ground(reading, {"text": "原文", "source_file": "book", "start": 0, "note_id": "n"})
    assert result["questions"] == ["旧疑问", "谁在追踪？"]
    assert result["reading_questions"][0]["kind"] == "plot_unrevealed"


def test_unrecorded_relation_does_not_default_to_changed():
    relation = Relation(subject="阳子", target="父亲", relation="女儿", trigger="未明确", quote="父亲")
    assert relation.record_kind == "unclassified"
    assert relation.previous == "未明确"
