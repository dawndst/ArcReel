"""Source-grounded second pass before an extracted fragment becomes Note memory."""

import json

from lib.novel_workflow import store
from lib.novel_workflow.models import Reading


def draft_claims(value):
    if isinstance(value, list):
        return [draft_claims(v) for v in value]
    if isinstance(value, dict):
        return {k: draft_claims(v) for k, v in value.items() if k not in {"id", "evidence"}}
    return value


async def audit(path, generator, extracted, part, seed_ids, identity_ids):
    import asyncio

    from lib.novel_workflow.service import ask, ground

    rules = await asyncio.to_thread(store.effective_rule, path, "read_review")
    return await ask(
        path,
        generator,
        Reading,
        rules
        + "\n抽取审核材料："
        + json.dumps(
            {
                "source": part["text"],
                "surrounding_context": {
                    "before": part.get("before_context", ""),
                    "after": part.get("after_context", ""),
                },
                "draft": draft_claims(extracted),
            },
            ensure_ascii=False,
        ),
        lambda value: ground(value, part, seed_ids, identity_ids) if value.complete else reject_incomplete(),
        grow_output=True,
        max_output_tokens=min(getattr(generator, "max_output_tokens", 24000), max(12000, len(part["text"]) * 4)),
    )


def reject_incomplete():
    raise ValueError("抽取审核必须返回完整修订稿；无法确认的结论保留未判定及原因，不能以未完成代替审核")
