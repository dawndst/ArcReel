"""Structured model stages with durable candidates and versioned field-only repairs."""

import asyncio
import json
from copy import deepcopy

from pydantic import Field, ValidationError

from lib.backends.text_backends.base import TextGenerationRequest, TextOutputTruncatedError
from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_workflow import store
from lib.novel_workflow.cancellation import check_stop
from lib.novel_workflow.common import digest, now
from lib.novel_workflow.models import StrictModel
from lib.novel_workflow.storage import load_json

REPAIR_LIMIT = 3


class ContractError(ValueError):
    def __init__(self, issues):
        self.issues = issues
        super().__init__("；".join(i["message"] for i in issues))


class StageRepairRequired(RuntimeError):
    """A retained stage needs local repair; never restart its enclosing generation."""


class FieldEdit(StrictModel):
    path: list[str | int] = Field(min_length=1)
    operation: str = Field(pattern="^(replace|remove)$")
    value_json: str


class FieldPatch(StrictModel):
    base_revision: str
    edits: list[FieldEdit] = Field(min_length=1)


def apply_patch(candidate, patch, issues):
    if patch.base_revision != digest(candidate):
        raise ValueError("局部修订版本不匹配")
    allowed = {tuple(i["path"]): i for i in issues}
    updated, seen = deepcopy(candidate), set()
    for edit in patch.edits:
        key = tuple(edit.path)
        if key not in allowed or key in seen:
            raise ValueError("只能修订列出的错误字段，不能覆盖其他镜头")
        seen.add(key)
        target = updated
        for part in edit.path[:-1]:
            target = target[part]
        final = edit.path[-1]
        if edit.operation == "remove":
            if isinstance(target, dict) and allowed[key].get("type") == "extra_forbidden":
                del target[final]
            elif isinstance(target, list) and allowed[key].get("type") == "unsafe_proposal":
                target[final] = None
            else:
                raise ValueError("仅允许移除多余字段或明确无效的审核提议")
        else:
            replacement = json.loads(edit.value_json)
            if edit.path == ["shots"] and isinstance(replacement, list):
                incoming = {s.get("key"): s for s in replacement if isinstance(s, dict)}
                for i, shot in enumerate(candidate.get("shots", [])):
                    invalid = any(tuple(issue["path"][:2]) == ("shots", i) for issue in issues)
                    if not invalid and isinstance(shot, dict) and incoming.get(shot.get("key")) != shot:
                        raise ValueError("补充遗漏镜头时必须原样保留已正确镜头")
            target[final] = replacement
    if isinstance(updated, dict) and "corrections" in updated:
        updated["corrections"] = [item for item in updated["corrections"] if item is not None]
    return updated


def errors(exc):
    if isinstance(exc, ContractError):
        return exc.issues
    return [{"path": list(e["loc"]), "message": e["msg"], "type": e["type"]} for e in exc.errors()]


async def request(generator, schema, prompt, project_name, output_limit):
    from lib.novel_workflow.service import output_schema, strip_json_code_fences

    while True:
        check_stop()
        try:
            response = await generator.generate(
                TextGenerationRequest(
                    prompt=prompt, max_output_tokens=output_limit, response_schema=output_schema(schema)
                ),
                project_name=project_name,
                require_complete=True,
            )
        except TextOutputTruncatedError:
            ceiling = min(getattr(generator, "max_output_tokens", 48000), 48000)
            if output_limit >= ceiling:
                raise
            output_limit = min(output_limit * 2, ceiling)
            continue
        return json.loads(strip_json_code_fences(response.text))


async def run(path, generator, schema, rule, material, key, validate, *, source_lookup=None, output_limit=14000):
    """Repair exact fields; source lookups add evidence rather than replace a draft."""
    fidelity = await asyncio.to_thread(store.effective_rule, path, "fidelity")
    rule = fidelity + "\n" + rule
    folder = store.root(path) / "scene_stages"
    target = folder / f"{key}.json"
    state = (
        await asyncio.to_thread(load_json, target)
        if await asyncio.to_thread(target.exists)
        else {
            "candidate": None,
            "lookups": {},
            "repairs": [],
            "status": "pending",
            "repair_limit": REPAIR_LIMIT,
        }
    )
    if state["status"] == "complete":
        try:
            return validate(schema.model_validate(state["candidate"]))
        except (ValidationError, ContractError):
            state["status"] = "repair_required"

    async def save():
        state["updated_at"] = now()
        await run_noninterruptible_sync(store.write, target, state)

    attempts = 0
    while True:
        check_stop()
        if state["candidate"] is None:
            prompt = rule + "\n阶段材料：" + json.dumps({**material, "reread": state["lookups"]}, ensure_ascii=False)
            try:
                state["candidate"] = await request(generator, schema, prompt, path.name, output_limit)
            except json.JSONDecodeError as exc:
                state.update(status="invalid_json", error=str(exc))
                await save()
                raise StageRepairRequired("模型未返回可解析的结构化结果，已保存阶段状态；可继续本单元。") from exc
            await save()
        try:
            parsed = schema.model_validate(state["candidate"], context={"model_output": True})
            requested = getattr(parsed, "source_requests", [])
            if requested:
                if not source_lookup or not (fresh := set(requested) - set(state["lookups"])):
                    raise ContractError(
                        [
                            {
                                "path": ["source_requests"],
                                "message": "原文已提供或无法回读，请完成当前结果并保留仍未解决的问题",
                            }
                        ]
                    )
                if len(state["lookups"]) + len(fresh) > 40 or state.get("lookup_rounds", 0) >= 2:
                    raise ContractError(
                        [
                            {
                                "path": ["source_requests"],
                                "message": "本阶段最多回读2轮、40个来源；请依据已提供材料完成并标注疑点",
                            }
                        ]
                    )
                found = source_lookup(fresh)
                state["lookup_rounds"] = state.get("lookup_rounds", 0) + 1
                state["lookups"].update(found)
                state.update(candidate=None, status="rereading")
                await save()
                continue
            result = validate(parsed)
            state.update(status="complete", issues=[])
            await save()
            return result
        except (ValidationError, ContractError) as exc:
            issues = errors(exc)
        state.update(status="repair_required", issues=issues)
        await save()
        if attempts >= REPAIR_LIMIT:
            raise StageRepairRequired(
                "本单元仍需局部修订，已保留其他成果：" + "；".join(i["message"] for i in issues)[:800]
            )
        patch_rule = await asyncio.to_thread(store.effective_rule, path, "scene_patch")
        prompt = (
            fidelity
            + "\n"
            + patch_rule
            + "\n局部修订材料："
            + json.dumps(
                {
                    "base_revision": digest(state["candidate"]),
                    "issues": issues,
                    "candidate": state["candidate"],
                    "context": material,
                    "reread": state["lookups"],
                    "previous_repair_feedback": state["repairs"][-2:],
                },
                ensure_ascii=False,
            )
        )
        try:
            patch = FieldPatch.model_validate(
                await request(generator, FieldPatch, prompt, path.name, min(output_limit, 8000))
            )
            candidate = apply_patch(state["candidate"], patch, issues)
            if candidate == state["candidate"]:
                raise ValueError("提交值与原值相同，没有修复问题；请使用错误提示中的合法ID或撤回无依据建议")
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            attempts += 1
            state["repairs"].append({"accepted": False, "error": str(exc)[:500]})
            await save()
            continue
        state["repairs"].append({"accepted": True, "paths": [e.path for e in patch.edits]})
        state["candidate"] = candidate
        attempts += 1
        await save()
