"""Source-grounded second pass before an extracted fragment becomes Note memory."""

import json

from lib.novel_workflow import store
from lib.novel_workflow.models import Reading
from lib.novel_workflow.reading_patches import ReviewEdits, apply, material


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

    async def validate(value):
        from lib.novel_workflow.quote_locations import resolve

        value = apply(draft, value)
        value = await resolve(path, generator, value, part)
        return ground(value, part, seed_ids, identity_ids)

    draft = draft_claims(extracted)
    protocol = await asyncio.to_thread(store.effective_rule, path, "read_review_patch")
    return await ask(
        path,
        generator,
        ReviewEdits,
        rules.replace("返回 complete=true 的完整结果，不只返回差异。", "完成所有栏目审查后返回complete=true。")
        + protocol
        + "\n抽取审核材料："
        + json.dumps(
            {
                "source": part["text"],
                "surrounding_context": {
                    "before": part.get("before_context", ""),
                    "after": part.get("after_context", ""),
                },
                **material(draft),
                "record_schema": Reading.model_json_schema(),
            },
            ensure_ascii=False,
        ),
        validate,
        grow_output=True,
        max_output_tokens=min(getattr(generator, "max_output_tokens", 24000), max(12000, len(part["text"]) * 4)),
    )
