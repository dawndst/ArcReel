"""Evidence-backed editorial proposals; adoption reuses ArcReel's merge transaction."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from lib.backends.text_generator import TextGenerator
from lib.episode.episode_ledger import has_downstream_products, parse_source_range
from lib.infra.async_thread import run_noninterruptible_sync
from lib.infra.json_io import load_json
from lib.novel_understanding import service, store
from lib.novel_understanding.models import EditorialDecision


def entries(project: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {k: e.get(k) for k in ("episode", "source_range", "title", "hook", "outline")}
        for e in project.get("episodes", [])
        if parse_source_range(e)
    ]


def basis(project: dict[str, Any], source: store.BookSource, episode: int) -> str:
    ordered = sorted(
        entries(project), key=lambda e: (source.order[e["source_range"]["source_file"]], e["source_range"]["start"])
    )
    index = next((i for i, e in enumerate(ordered) if e["episode"] == episode), None)
    relevant = ordered[index : index + 2] if index is not None else []
    return store.digest([source.run_id, relevant, project.get("episode_target_duration")])


def report_path(path: Path, report_id: str) -> Path:
    if len(report_id) != 64 or any(c not in "0123456789abcdef" for c in report_id):
        raise store.NovelUnderstandingError("Invalid editorial report identifier")
    return store.root(path) / "editorial" / (report_id + ".json")


def reports(path: Path, project: dict[str, Any]) -> list[dict[str, Any]]:
    if not service.applicable(project):
        return []
    source = store.source_snapshot(path, project)
    directory = store.root(path) / "editorial"
    return [
        value
        for file in sorted(directory.glob("*.json"))
        if (value := load_json(file)).get("basis") == basis(project, source, value["episode"])
    ]


async def inspect_episodes(path: Path, project: dict[str, Any], generator: TextGenerator) -> list[dict[str, Any]]:
    memory = await service.ensure(path, project, generator)
    if memory is None or project.get("content_mode") != "drama":
        return []
    existing = await asyncio.to_thread(reports, path, project)
    results = []
    ordered = sorted(
        entries(project),
        key=lambda e: (memory.source.order[e["source_range"]["source_file"]], e["source_range"]["start"]),
    )
    for index, entry in enumerate(ordered):
        episode = entry["episode"]
        signature = basis(project, memory.source, episode)
        cached = next((r for r in existing if r["episode"] == episode), None)
        if cached:
            results.append(cached)
            continue
        following = ordered[index + 1] if index + 1 < len(ordered) else None
        cutoff = service.episode_cutoff(project, episode)
        assert cutoff is not None
        end = service.episode_cutoff(project, following["episode"]) if following else cutoff
        assert end is not None
        end_file, end_offset = end
        text = service.encode([entry, following])
        facts = [f for f in memory.facts if f.subject in text or any(n in text for n in f.related_entities)]
        # Budget evidence selection rather than silently truncating the book or episode ledger.
        facts = sorted(
            facts, key=lambda f: (memory.visible(f, end_file, end_offset), bool(f.narrative_functions)), reverse=True
        )[:80]
        if not facts:
            continue
        data = {
            "current": entry,
            "next": following,
            "current_cutoff": cutoff,
            "merged_cutoff": end,
            "target_seconds": project.get("episode_target_duration"),
            "facts": [f.model_dump() for f in facts],
        }
        decision = await service.ask(
            path,
            memory.source,
            generator,
            EditorialDecision,
            memory.source.rules["editorial"] + "\n" + service.encode(data),
            "editorial",
        )
        if decision.action == "merge_next" and following is None:
            raise store.NovelUnderstandingError("Editorial proposal has no next episode to merge")
        known = {f.id: f for f in facts}
        if not all(fid in known for fid in decision.evidence_ids):
            raise store.NovelUnderstandingError("Editorial proposal cites unknown evidence")
        final_cutoff = end if decision.action == "merge_next" else cutoff
        failures = await service.review(
            path,
            memory,
            generator,
            item_id=str(episode),
            cutoff=final_cutoff,
            content=decision.model_dump(),
            stage="editorial",
        )
        if failures:
            raise store.NovelUnderstandingError("Editorial proposal revealed future information; retry review")
        report_id = store.digest([signature, episode, decision.model_dump()])
        value = {
            "id": report_id,
            "basis": signature,
            "run_id": memory.source.run_id,
            "episode": episode,
            "next_episode": following["episode"] if following else None,
            "decision": decision.model_dump(),
            "evidence": [
                known[fid].evidence.model_dump()
                for fid in decision.evidence_ids
                if memory.visible(known[fid], *final_cutoff)
            ],
        }
        await asyncio.to_thread(service.assert_current, path, memory.source)
        await run_noninterruptible_sync(service.save_json, report_path(path, report_id), value)
        results.append(value)
    return results


def adoption(path: Path, report_id: str):
    report = load_json(report_path(path, report_id))
    episode = report["episode"]
    decision = EditorialDecision.model_validate(report["decision"])

    def validate(project: dict[str, Any]) -> None:
        if (
            not service.applicable(project)
            or basis(project, store.source_snapshot(path, project), episode) != report["basis"]
        ):
            raise store.NovelUnderstandingError("Editorial proposal is out of date; review the current episodes again")

    def apply(project: dict[str, Any]) -> None:
        from lib.script.script_review import mark_ledger_stale

        entry = next(e for e in project["episodes"] if e["episode"] == episode)
        if has_downstream_products(path, episode, entry):
            mark_ledger_stale(path, project, entry, episode)
        entry.update(
            title=decision.title,
            hook=decision.hook,
            outline={"story_beats": decision.story_beats, "next_episode_teaser": None},
        )
        entry["adaptation_decision"] = {
            "report_id": report_id,
            "run_id": report.get("run_id"),
            "outline_digest": store.digest([entry.get("title"), entry.get("hook"), entry.get("outline")]),
            "source_range": entry.get("source_range"),
            "must_film": decision.must_film,
            "compress": decision.compress,
            "omit": decision.omit,
            "preserve_setup": decision.preserve_setup,
        }

    return report, validate, apply


def accepted_constraints(project: dict[str, Any], episode: int, run_id: str | None = None) -> str:
    entry = next((e for e in project.get("episodes", []) if e.get("episode") == episode), {})
    decision = entry.get("adaptation_decision")
    if (
        not decision
        or decision.get("source_range") != entry.get("source_range")
        or decision.get("outline_digest") != store.digest([entry.get("title"), entry.get("hook"), entry.get("outline")])
        or (run_id is not None and decision.get("run_id") != run_id)
    ):
        return ""
    return (
        "\n<accepted_adaptation>"
        + service.encode(decision)
        + "</accepted_adaptation>\n严格遵循已采纳取舍：省略项不得重新写回；伏笔保留但不提前解释。"
    )
