"""Optional, project-local novel memory. Writers receive evidence up to their cutoff only."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ValidationError

from lib.backends.text_backends.base import TextGenerationRequest, resolve_schema, structured_fallback_reason
from lib.backends.text_generator import TextGenerator
from lib.episode.episode_ledger import parse_source_range
from lib.infra.async_thread import run_noninterruptible_sync, run_sync_transaction
from lib.infra.json_io import atomic_write_json, load_json
from lib.infra.text_utils import strip_json_code_fences
from lib.novel_understanding import store
from lib.novel_understanding.models import BookSynthesis, ReadChunk, ReadingDraft, ReviewDraft, StoryFact

stop_requested: ContextVar[Callable[[], bool] | None] = ContextVar("novel_stop_requested", default=None)


class NovelReadingInterrupted(store.NovelUnderstandingError):
    """A cooperative stop preserves the current paid response and completed chunks."""


def check_stop() -> None:
    check = stop_requested.get()
    if check is not None and check():
        raise NovelReadingInterrupted("Novel reading stopped; completed chunks are saved and can be resumed")


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


@dataclass
class Memory:
    source: store.BookSource
    chunks: list[ReadChunk]
    synthesis: BookSynthesis

    @property
    def facts(self) -> list[StoryFact]:
        return list({fact.id: fact for chunk in self.chunks for fact in chunk.facts}.values())

    def visible(self, fact: StoryFact, source_file: str, end: int) -> bool:
        order = self.source.order
        return (order[fact.evidence.source_file], fact.evidence.end) <= (order[source_file], end)

    def writer_context(self, source_file: str, end: int, text: str) -> str:
        # Summaries, entity names and model-written statements may incorporate later knowledge
        # inside a reading chunk. Only verified original quotations cross the writer boundary.
        visible = [f for f in self.facts if self.visible(f, source_file, end)]
        visible.sort(
            key=lambda f: (
                f.subject in text,
                f.category in {"state", "appearance", "world"},
                self.source.order[f.evidence.source_file],
                f.evidence.end,
            ),
            reverse=True,
        )
        quotes = []
        budget = 16000
        for fact in visible:
            quote = fact.evidence.model_dump()
            size = len(encode(quote))
            if size > budget:
                continue
            quotes.append(quote)
            budget -= size
        return (
            "\n<novel_evidence>"
            + encode(quotes)
            + "</novel_evidence>\n"
            + (
                "只根据本集原文和以上已揭示的原文证据创作。证据中的人物说法不等于客观事实。"
                "区分读者已知与角色已知；年龄、形态、服装、伤情按当前剧情状态，不提前展示未来状态。"
                "不使用你对作品的外部知识，不提前解释身份或伏笔。原文是资料范围，不要求逐段拍摄；"
                "保留因果、关系变化和伏笔，压缩重复说明与过场。安静场景不等于没有叙事价值。"
            )
        )


def applicable(project: dict[str, Any]) -> bool:
    from lib.episode.source_kinds import project_overview_source_kind

    return (
        store.enabled(project)
        and bool(project.get("whole_source_files"))
        and project_overview_source_kind(project) == "novel"
    )


def assert_current(path: Path, source: store.BookSource) -> None:
    from lib.project.project_manager import ProjectManager

    project = ProjectManager.for_project_dir(path).load_project(path.name)
    if not applicable(project) or store.source_snapshot(path, project).run_id != source.run_id:
        raise store.NovelUnderstandingError("Novel source, rules or switch changed; retry with the current project")


async def ask(
    path: Path, source: store.BookSource, generator: TextGenerator, schema: type[BaseModel], prompt: str, label: str
) -> Any:
    # Keep wire schemas simple across gateways; enforce the complete contract locally.
    # Some gateways report complex JSON-schema rejection as an opaque retryable 503.
    instruction = "\n只输出一个 JSON 对象，不写 Markdown 或解释。严格符合以下 JSON Schema：\n" + encode(
        schema.model_json_schema()
    )
    failure = ""
    for _attempt in range(3):
        check_stop()
        result = await generator.generate(
            TextGenerationRequest(
                prompt=prompt + instruction + failure, max_output_tokens=12000 if schema is ReadingDraft else 6000
            ),
            project_name=path.name,
            require_complete=True,
        )
        await run_noninterruptible_sync(store.save_response, path, source, label + "-" + uuid4().hex, result.text)
        try:
            return schema.model_validate_json(strip_json_code_fences(result.text))
        except ValidationError as exc:
            failure = "\n上一轮 JSON 不符合结构要求，请修正：" + str(exc)[:2500]
    raise store.NovelUnderstandingError("Model returned invalid novel data after three attempts; responses preserved")


def save_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, value)


async def ensure(path: Path, project: dict[str, Any], generator: TextGenerator) -> Memory | None:
    if not applicable(project):
        return None
    from lib.project.project_manager import ProjectManager

    manager = await asyncio.to_thread(ProjectManager.for_project_dir, path)
    await run_sync_transaction(store.rules, path, install=True)
    async with manager.async_file_lock(store.root(path) / "reading.lock"):
        project = await asyncio.to_thread(manager.load_project, path.name)
        if not applicable(project):
            return None
        source = await asyncio.to_thread(store.source_snapshot, path, project)
        completed: list[ReadChunk] = []
        try:
            for chunk in source.chunks:
                check_stop()
                await asyncio.to_thread(assert_current, path, source)
                value = await asyncio.to_thread(store.cached_chunk, path, source, chunk)
                if value is None:
                    await run_sync_transaction(store.write_state, path, source, phase="reading", completed=completed)
                    failure = ""
                    for attempt in range(3):
                        draft = await ask(
                            path,
                            source,
                            generator,
                            ReadingDraft,
                            source.rules["reading"]
                            + "\n前段记忆仅用于理解代词，新事实仍须由当前原文直接支持：\n"
                            + encode([c.summary for c in completed[-2:]])
                            + "\n"
                            + failure
                            + "\n<source>\n"
                            + chunk.text
                            + "\n</source>",
                            f"read-{chunk.index}-{attempt}",
                        )
                        try:
                            value = store.ground_chunk(chunk, draft)
                            break
                        except store.NovelUnderstandingError as exc:
                            failure = str(exc)
                    if value is None:
                        raise store.NovelUnderstandingError(failure)
                    await run_noninterruptible_sync(store.save_chunk, path, source, chunk, value)
                completed.append(value)
            await asyncio.to_thread(assert_current, path, source)
            await run_sync_transaction(store.write_state, path, source, phase="synthesizing", completed=completed)
            # A bounded reduction tree; full atomic facts remain on disk independently.
            nodes = [c.summary for c in completed]
            level = 0
            synthesis = BookSynthesis(synopsis="", genre="", theme="", world_setting="")
            while nodes:
                next_nodes = []
                for start in range(0, len(nodes), 8):
                    inputs = nodes[start : start + 8]
                    cache = store.run_dir(path, source) / "synthesis" / (store.digest(inputs) + ".json")
                    if await asyncio.to_thread(cache.exists):
                        synthesis = BookSynthesis.model_validate(await asyncio.to_thread(load_json, cache))
                    else:
                        synthesis = await ask(
                            path,
                            source,
                            generator,
                            BookSynthesis,
                            source.rules["synthesis"] + "\n" + encode(inputs),
                            f"synthesis-{level}-{start}",
                        )
                        await run_noninterruptible_sync(save_json, cache, synthesis.model_dump())
                    next_nodes.append(encode(synthesis.model_dump()))
                if len(next_nodes) == 1:
                    break
                nodes = next_nodes
                level += 1
            await asyncio.to_thread(assert_current, path, source)
            await run_sync_transaction(save_json, store.run_dir(path, source) / "book.json", synthesis.model_dump())
            await run_sync_transaction(store.write_state, path, source, phase="ready", completed=completed)
            return Memory(source, completed, synthesis)
        except BaseException as exc:
            await run_noninterruptible_sync(
                store.write_state,
                path,
                source,
                phase="interrupted" if isinstance(exc, (asyncio.CancelledError, NovelReadingInterrupted)) else "failed",
                completed=completed,
                error=str(exc)[:1500],
            )
            raise


def episode_cutoff(project: dict[str, Any], episode: int) -> tuple[str, int] | None:
    entry = next((e for e in project.get("episodes", []) if e.get("episode") == episode), {})
    span = parse_source_range(entry)
    return (span.end_file or span.source_file, span.end) if span else None


def scoped_inputs(inputs: dict[str, Any], memory: Memory, cutoff: tuple[str, int], text: str) -> dict[str, Any]:
    scoped = dict(inputs)
    # Global overview and accumulated asset descriptions are author-side data, not episode-safe evidence.
    scoped["project_overview"] = {}
    scoped["next_episode_outline"] = None
    for bucket in ("characters", "scenes", "props"):
        scoped[bucket] = {name: {"description": ""} for name in inputs.get(bucket, {}) if name in text}
    return scoped


def relevant_facts(memory: Memory, rendered: str, cutoff: tuple[str, int]) -> list[StoryFact]:
    """Bound review cost with separate past/future budgets; names and textual overlap drive retrieval."""
    bigrams = {rendered[i : i + 2] for i in range(len(rendered) - 1)}
    scored = []
    for fact in memory.facts:
        related = fact.subject in rendered or any(name in rendered for name in fact.related_entities)
        if not related and fact.category != "world":
            continue
        text = fact.statement + fact.evidence.quote
        score = sum(text[i : i + 2] in bigrams for i in range(len(text) - 1)) / max(len(text), 1)
        scored.append((score, fact))
    scored.sort(key=lambda item: item[0], reverse=True)
    past = [f for _, f in scored if memory.visible(f, *cutoff)][:48]
    future = [f for _, f in scored if not memory.visible(f, *cutoff)][:48]
    return past + future


async def review(
    path: Path,
    memory: Memory,
    generator: TextGenerator,
    *,
    item_id: str,
    cutoff: tuple[str, int],
    content: Any,
    stage: str,
) -> list[str]:
    check_path = (
        store.run_dir(path, memory.source) / "checks" / (store.digest([stage, item_id, cutoff, content]) + ".json")
    )
    if await asyncio.to_thread(check_path.exists):
        cached = await asyncio.to_thread(load_json, check_path)
        result = ReviewDraft.model_validate({"issues": cached["issues"]})
        await asyncio.to_thread(assert_current, path, memory.source)
        return safe_feedback(result)
    rendered = encode(content)
    facts = await asyncio.to_thread(relevant_facts, memory, rendered, cutoff)
    # Every selected fact is checked, in bounded batches. Future facts never enter repair prompts.
    issues = []
    for start in range(0, len(facts), 32):
        selected = facts[start : start + 32]
        data = {
            "stage": stage,
            "items": [{"item_id": item_id, "reader_cutoff": cutoff, "content": content}],
            "source_order": memory.source.order,
            "facts": [f.model_dump() for f in selected],
        }
        result = await ask(
            path, memory.source, generator, ReviewDraft, memory.source.rules["review"] + "\n" + encode(data), "review"
        )
        by_id = {f.id: f for f in selected}
        for issue in result.issues:
            if issue.item_id != item_id or issue.offending_text not in rendered or not issue.fact_ids:
                continue
            if not all(fid in by_id for fid in issue.fact_ids):
                continue
            if issue.kind == "unnecessary_episode":
                continue  # Editorial recommendations require human adoption, not automatic rejection.
            if issue.kind == "premature_reveal" and not any(
                not memory.visible(by_id[fid], *cutoff) for fid in issue.fact_ids
            ):
                continue
            if issue.kind in {"canon_conflict", "state_mismatch"} and not any(
                by_id[fid].assertion == "established" for fid in issue.fact_ids
            ):
                continue
            issues.append(issue)
    await run_noninterruptible_sync(
        save_json,
        check_path,
        {"stage": stage, "item_id": item_id, "issues": [i.model_dump() for i in issues]},
    )
    await asyncio.to_thread(assert_current, path, memory.source)
    return safe_feedback(ReviewDraft(issues=issues))


def safe_feedback(result: ReviewDraft) -> list[str]:
    return [
        "删除或改写这段存在一致性或提前揭示问题的内容，仅依据当前集原文重写，不猜测隐藏真相：" + issue.offending_text
        for issue in result.issues
    ]


@dataclass
class ProductionGuard:
    path: Path
    memory: Memory
    generator: TextGenerator
    episode: int
    cutoff: tuple[str, int]
    context: str
    episode_basis: str

    async def check(self, content: Any) -> list[str]:
        from lib.project.project_manager import ProjectManager

        manager = await asyncio.to_thread(ProjectManager.for_project_dir, self.path)
        current = await asyncio.to_thread(manager.load_project, self.path.name)
        if episode_basis(current, self.episode) != self.episode_basis:
            raise store.NovelUnderstandingError("Episode source or outline changed during generation; retry")
        return await review(
            self.path,
            self.memory,
            self.generator,
            item_id=str(self.episode),
            cutoff=self.cutoff,
            content=content,
            stage="script",
        )

    async def generate(self, request: TextGenerationRequest):
        failure = ""
        from dataclasses import replace

        for _attempt in range(3):
            schema_instruction = (
                "\n只输出符合以下 Schema 的 JSON，不写 Markdown：\n" + encode(resolve_schema(request.response_schema))
                if request.response_schema is not None
                else ""
            )
            result = await self.generator.generate(
                replace(
                    request, response_schema=None, prompt=request.prompt + self.context + schema_instruction + failure
                ),
                project_name=self.path.name,
                require_complete=True,
            )
            await run_noninterruptible_sync(
                store.save_response,
                self.path,
                self.memory.source,
                f"production-{self.episode}-{uuid4().hex}",
                result.text,
            )
            if request.response_schema is not None:
                invalid = structured_fallback_reason(result.text, request.response_schema)
                if invalid:
                    failure = "\n上一轮结构不符合要求，请严格按 Schema 输出：" + invalid
                    continue
            try:
                content = json.loads(strip_json_code_fences(result.text))
            except json.JSONDecodeError:
                failure = "\n上一轮不是有效 JSON，请修正。"
                continue
            problems = await self.check(content)
            if not problems:
                return result
            failure = "\n" + "\n".join(problems)
        raise store.NovelUnderstandingError(
            "Novel consistency check failed after three attempts; responses were preserved"
        )


def episode_basis(project: dict[str, Any], episode: int) -> str:
    entry = next((e for e in project.get("episodes", []) if e.get("episode") == episode), {})
    return store.digest({k: entry.get(k) for k in ("source_range", "outline", "title", "hook", "adaptation_decision")})


async def prepare(
    path: Path,
    project: dict[str, Any],
    episode: int,
    text: str,
    inputs: dict[str, Any],
    *,
    dry_run: bool = False,
    generator: TextGenerator | None = None,
) -> tuple[dict[str, Any], ProductionGuard | None]:
    cutoff = episode_cutoff(project, episode)
    if not applicable(project) or cutoff is None:
        return inputs, None
    from lib.backends.providers import CallPurpose
    from lib.backends.text_backends.base import TextTaskType
    from lib.novel_understanding.editorial import accepted_constraints

    if dry_run:
        scoped = dict(inputs)
        scoped["project_overview"] = {}
        scoped["next_episode_outline"] = None
        for bucket in ("characters", "scenes", "props"):
            scoped[bucket] = {name: {"description": ""} for name in inputs.get(bucket, {}) if name in text}
        return scoped, None
    if generator is None:
        generator = await TextGenerator.create(TextTaskType.SCRIPT, path.name, purpose=CallPurpose.SCRIPT_GENERATION)
    memory = await ensure(path, project, generator)
    if memory is None:
        return inputs, None
    context = memory.writer_context(*cutoff, text) + accepted_constraints(project, episode, memory.source.run_id)
    return scoped_inputs(inputs, memory, cutoff, text), ProductionGuard(
        path, memory, generator, episode, cutoff, context, episode_basis(project, episode)
    )


async def generate_project_overview(manager: Any, name: str) -> dict:
    project = await asyncio.to_thread(manager.load_project, name)
    if not applicable(project):
        return await manager.generate_overview(name)
    from lib.backends.providers import CallPurpose
    from lib.backends.text_backends.base import TextTaskType

    generator = await TextGenerator.create(TextTaskType.OVERVIEW, name, purpose=CallPurpose.PROJECT_OVERVIEW)
    path = await asyncio.to_thread(manager.get_project_path, name)
    memory = await ensure(path, project, generator)
    if memory is None:
        return await manager.generate_overview(name)

    def source_check(current: dict[str, Any]) -> None:
        if not applicable(current) or store.source_snapshot(path, current).run_id != memory.source.run_id:
            raise store.NovelUnderstandingError("Source changed while producing the overview; retry")

    sample = memory.source.docs[0].text[:2000] if memory.source.docs else ""
    return await manager.generate_overview(
        name,
        source_content_override=encode(memory.synthesis.model_dump()) + "\n原文语言样本：\n" + sample,
        source_check=source_check,
    )
