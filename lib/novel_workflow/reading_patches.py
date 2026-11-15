"""Apply source-review edits against one immutable extraction snapshot."""

import json
from copy import deepcopy
from typing import Literal

from pydantic import Field

from lib.novel_workflow.common import digest
from lib.novel_workflow.models import Reading, StrictModel

BUCKETS = (
    "assets",
    "changes",
    "events",
    "aliases",
    "relations",
    "threads",
    "highlights",
    "reading_questions",
    "questions",
)


class ReviewEdit(StrictModel):
    operation: Literal["replace", "remove", "append"]
    target: str = Field(min_length=1, max_length=100)
    value_json: str = Field(
        default="", max_length=50000, description="单条替换/新增记录的JSON字符串；summary为JSON字符串值；remove时为空"
    )
    reason: str = Field(min_length=1, max_length=1500)


class ReviewEdits(StrictModel):
    snapshot: str
    complete: bool
    reviewed_sections: list[str]
    edits: list[ReviewEdit] = Field(default_factory=list, max_length=300)


def material(draft):
    return {"snapshot": digest(draft), "draft": draft, "review_sections": ["summary", *BUCKETS]}


def apply(draft, review):
    if not review.complete or review.snapshot != digest(draft):
        raise ValueError("审核未完成或原稿版本不匹配")
    expected = {"summary", *BUCKETS}
    if len(review.reviewed_sections) != len(expected) or set(review.reviewed_sections) != expected:
        raise ValueError("必须审查全部栏目，包括未修改和空栏目")
    replacements, removals, additions, seen = {}, set(), [], set()
    for edit in review.edits:
        if edit.operation == "append":
            if edit.target not in BUCKETS:
                raise ValueError("只能向已知列表新增一条记录")
        else:
            if edit.target in seen:
                raise ValueError("同一原始记录只能修改一次")
            seen.add(edit.target)
            if edit.target == "summary":
                if edit.operation != "replace":
                    raise ValueError("摘要只能替换，不能删除")
            else:
                bucket, sep, index = edit.target.partition(".")
                if (
                    not sep
                    or bucket not in BUCKETS
                    or not index.isdigit()
                    or str(int(index)) != index
                    or int(index) >= len(draft[bucket])
                ):
                    raise ValueError("只能修改明确编号的原始记录")
        if edit.operation == "remove":
            if edit.value_json:
                raise ValueError("删除操作不得携带替换值")
            removals.add(edit.target)
            continue
        try:
            value = json.loads(edit.value_json)
        except (ValueError, TypeError) as exc:
            raise ValueError("修订值必须是合法JSON") from exc

        def protected(item):
            if isinstance(item, dict):
                return any(k in {"id", "evidence"} or protected(v) for k, v in item.items())
            return isinstance(item, list) and any(protected(v) for v in item)

        if protected(value):
            raise ValueError("模型不能直接指定记录ID或原文坐标")
        if edit.operation == "replace" and edit.target != "summary":
            bucket, _, index = edit.target.partition(".")
            original = draft[bucket][int(index)]
            if isinstance(original, dict) and (not isinstance(value, dict) or not original.keys() <= value.keys()):
                raise ValueError("替换记录须保留全部字段，不能依赖默认值静默清空对白或状态")
        if edit.operation == "append":
            additions.append((edit.target, value))
        else:
            replacements[edit.target] = value
    result = deepcopy(draft)
    result["summary"] = replacements.get("summary", result["summary"])
    for bucket in BUCKETS:
        result[bucket] = [
            replacements.get(f"{bucket}.{i}", item)
            for i, item in enumerate(result[bucket])
            if f"{bucket}.{i}" not in removals
        ]
    for bucket, value in additions:
        result[bucket].append(value)
    return Reading.model_validate(result, context={"model_output": True})
