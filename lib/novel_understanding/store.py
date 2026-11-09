"""Synchronous storage primitives; asynchronous callers offload whole transactions."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.episode.episode_ledger import SourceDoc
from lib.episode.episode_sources import discover_sources, whole_source_files
from lib.infra.json_io import atomic_write_json, load_json
from lib.novel_understanding.models import Evidence, ReadChunk, ReadingDraft, StoryFact

SETTING_KEY = "novel_understanding_enabled"
STORE_VERSION = 1
CHUNK_CHARS = 20000
OVERLAP_CHARS = 1000
RULE_NAMES = ("reading", "synthesis", "review", "editorial")
BUILTIN_RULES = Path(__file__).parent / "rules"


class NovelUnderstandingError(RuntimeError):
    """Incomplete or ungrounded reading must not silently become production context."""


def enabled(project: Mapping[str, Any]) -> bool:
    return project.get(SETTING_KEY, True) is not False and project.get("content_mode") == "drama"


def digest(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat()


def root(project_path: Path) -> Path:
    return project_path / "novel_understanding"


def rules(project_path: Path, *, install: bool = False) -> dict[str, str]:
    directory = root(project_path) / "rules"
    if install:
        directory.mkdir(parents=True, exist_ok=True)
    result = {}
    for name in RULE_NAMES:
        path = directory / f"{name}.md"
        if path.exists():
            result[name] = path.read_text(encoding="utf-8")
        else:
            result[name] = (BUILTIN_RULES / f"{name}.md").read_text(encoding="utf-8")
            if install:
                # Exclusive creation preserves a concurrent creator's independent project rule.
                try:
                    with path.open("x", encoding="utf-8") as handle:
                        handle.write(result[name])
                except FileExistsError:
                    result[name] = path.read_text(encoding="utf-8")
    return result


@dataclass(frozen=True)
class Chunk:
    index: int
    source_file: str
    start: int
    end: int
    input_start: int
    text: str
    source_digest: str


@dataclass(frozen=True)
class BookSource:
    run_id: str
    docs: list[SourceDoc]
    chunks: list[Chunk]
    rules: dict[str, str]
    source_digest: str

    @property
    def total_chars(self) -> int:
        return sum(len(doc.text) for doc in self.docs)

    @property
    def order(self) -> dict[str, int]:
        return {doc.rel_path: index for index, doc in enumerate(self.docs)}


def source_snapshot(project_path: Path, project: Mapping[str, Any], *, chunk_chars: int = CHUNK_CHARS) -> BookSource:
    if chunk_chars < 1:
        raise ValueError("chunk_chars must be positive")
    expected = whole_source_files(project)
    docs = discover_sources(project_path, project)
    if [doc.rel_path for doc in docs] != expected:
        raise NovelUnderstandingError(
            "Registered source files are missing or unreadable; full-book coverage cannot be verified"
        )
    policy = rules(project_path)
    source_digest = digest([(doc.rel_path, doc.text) for doc in docs])
    run_id = digest({"source": source_digest, "rules": policy, "version": STORE_VERSION, "chunk_chars": chunk_chars})
    chunks = []
    for doc in docs:
        file_digest = digest(doc.text)
        for start in range(0, len(doc.text), chunk_chars):
            end = min(start + chunk_chars, len(doc.text))
            input_start = max(0, start - min(OVERLAP_CHARS, chunk_chars // 4))
            chunks.append(
                Chunk(len(chunks), doc.rel_path, start, end, input_start, doc.text[input_start:end], file_digest)
            )
    return BookSource(run_id, docs, chunks, policy, source_digest)


def run_dir(project_path: Path, source: BookSource) -> Path:
    return root(project_path) / "runs" / source.run_id


def read_state(project_path: Path) -> dict[str, Any]:
    path = root(project_path) / "status.json"
    if not path.exists():
        return {}
    value = load_json(path)
    if not isinstance(value, dict):
        raise NovelUnderstandingError("Invalid novel understanding status file")
    return value


def write_state(
    project_path: Path,
    source: BookSource,
    *,
    phase: str,
    completed: list[ReadChunk],
    error: str | None = None,
    partial: list[ReadChunk] | None = None,
) -> dict[str, Any]:
    directory = run_dir(project_path, source)
    directory.mkdir(parents=True, exist_ok=True)
    read_parts = [*completed, *(partial or [])]
    state = {
        "version": STORE_VERSION,
        "run_id": source.run_id,
        "source_digest": source.source_digest,
        "rules_digest": digest(source.rules),
        "phase": phase,
        "total_chunks": len(source.chunks),
        "completed_chunks": len(completed),
        "total_chars": source.total_chars,
        "read_chars": sum(chunk.end - chunk.start for chunk in read_parts),
        "facts_count": len({fact.id for chunk in read_parts for fact in chunk.facts}),
        "updated_at": now(),
        "error": error,
    }
    atomic_write_json(directory / "status.json", state)
    atomic_write_json(root(project_path) / "status.json", state)
    atomic_write_json(directory / "rules.json", source.rules)
    return state


def chunk_path(project_path: Path, source: BookSource, chunk: Chunk) -> Path:
    return run_dir(project_path, source) / "chunks" / f"{chunk.index:06d}.json"


def cached_chunk(
    project_path: Path, source: BookSource, chunk: Chunk, *, cache_path: Path | None = None
) -> ReadChunk | None:
    path = cache_path or chunk_path(project_path, source, chunk)
    if not path.exists():
        return None
    value = ReadChunk.model_validate(load_json(path))
    if (value.index, value.source_file, value.start, value.end, value.source_digest) != (
        chunk.index,
        chunk.source_file,
        chunk.start,
        chunk.end,
        chunk.source_digest,
    ):
        raise NovelUnderstandingError("Cached reading chunk does not match its source range")
    for fact in value.facts:
        evidence = fact.evidence
        start, end = evidence.start - chunk.input_start, evidence.end - chunk.input_start
        if (
            evidence.source_file != chunk.source_file
            or start < 0
            or end > len(chunk.text)
            or chunk.text[start:end] != evidence.quote
        ):
            raise NovelUnderstandingError("Cached reading evidence no longer matches the original text")
    return value


def ground_chunk(chunk: Chunk, draft: ReadingDraft) -> ReadChunk:
    facts = []
    for fact in draft.facts:
        quote = fact.evidence_quote
        start = chunk.text.find(quote)
        if start < 0 or chunk.text.find(quote, start + 1) >= 0:
            raise NovelUnderstandingError("Every fact needs a unique verbatim quotation inside this reading window")
        evidence = Evidence(
            source_file=chunk.source_file,
            start=chunk.input_start + start,
            end=chunk.input_start + start + len(quote),
            quote=quote,
        )
        data = fact.model_dump(exclude={"evidence_quote"})
        facts.append(
            StoryFact(id="F-" + digest({**data, "evidence": evidence.model_dump()})[:20], evidence=evidence, **data)
        )
    return ReadChunk(
        index=chunk.index,
        source_file=chunk.source_file,
        start=chunk.start,
        end=chunk.end,
        source_digest=chunk.source_digest,
        summary=draft.summary,
        facts=facts,
        open_questions=draft.open_questions,
    )


def save_chunk(project_path: Path, source: BookSource, chunk: Chunk, value: ReadChunk) -> None:
    path = chunk_path(project_path, source, chunk)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, value.model_dump())


def save_response(project_path: Path, source: BookSource, name: str, response_text: str) -> None:
    directory = run_dir(project_path, source) / "responses"
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_json(directory / f"{name}.json", {"text": response_text, "received_at": now()})


def status(project_path: Path, project: Mapping[str, Any]) -> dict[str, Any]:
    active = enabled(project)
    if not whole_source_files(project):
        return {
            "enabled": active,
            "supported": project.get("content_mode") == "drama",
            "phase": "no_source",
            "total_chars": 0,
            "read_chars": 0,
            "completed_chunks": 0,
            "total_chunks": 0,
        }
    source = source_snapshot(project_path, project)
    state = read_state(project_path)
    if state.get("run_id") != source.run_id:
        state = {
            "phase": "stale" if state else "not_started",
            "total_chars": source.total_chars,
            "read_chars": 0,
            "completed_chunks": 0,
            "total_chunks": len(source.chunks),
            "facts_count": 0,
        }
    return {
        **state,
        "enabled": active,
        "supported": project.get("content_mode") == "drama",
        "coverage": round(100 * state.get("read_chars", 0) / max(source.total_chars, 1), 2),
    }
