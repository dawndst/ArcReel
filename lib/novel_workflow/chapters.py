"""Deterministic chapter mapping; upper/middle/lower sections stay in one Note."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from lib.episode.episode_sources import discover_sources
from lib.novel_understanding.store import digest

CHAPTER = re.compile(
    r"第[零〇一二三四五六七八九十百千万两0-9０-９]+[章节回]|(?:序\s*章|楔子|尾声|终章|終章|正文[一二三四五六七八九十0-9]+|完结)|(?<!\S)[零〇一二三四五六七八九十百千万两0-9０-９]+章|\bChapter\s+[0-9IVXLCDM]+",
    re.I,
)
PART = re.compile(r"[（(]\s*([上中下])\s*[）)]|[·\s]+([上中下])$")
MARKDOWN = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
PLAIN = re.compile(
    r"^\s*((?:第[零〇一二三四五六七八九十百千万两0-9０-９]+[章节回]|序章|楔子|尾声|终章|Chapter\s+\d+)[^\n]{0,70})$",
    re.M | re.I,
)


def index(path: Path, project: dict) -> dict:
    docs = discover_sources(path, project)
    if not docs:
        raise ValueError("No registered novel source")
    sections = []
    skipped = []
    for doc in docs:
        headings = list(MARKDOWN.finditer(doc.text))
        if not any(CHAPTER.search(m[1]) for m in headings):
            headings = list(PLAIN.finditer(doc.text))
        if not headings or not any(CHAPTER.search(m[1]) for m in headings):
            raise ValueError(f"Cannot identify chapters in {doc.rel_path}; provide explicit chapter headings")
        volume = Path(doc.rel_path).stem
        for i, heading in enumerate(headings):
            title = heading[1].strip().lstrip("- ").strip()
            end = headings[i + 1].start() if i + 1 < len(headings) else len(doc.text)
            match = CHAPTER.search(title)
            body = doc.text[heading.end() : end].strip()
            unresolved = (
                not match
                and len(body) > 400
                and not any(word in title for word in ("版权", "目录", "目錄", "后记", "後記"))
            )
            if (not match and not unresolved) or any(word in title for word in ("版权", "目录", "目錄")):
                volume = title or volume
                skipped.append({"source_file": doc.rel_path, "start": heading.start(), "end": end, "title": title})
                continue
            chapter_start = match.start() if match else 0
            prefix = title[:chapter_start].strip(" -·")
            chapter_volume = prefix or volume
            canonical = PART.sub("", title[chapter_start:]).strip()
            sections.append(
                {
                    "volume": chapter_volume,
                    "chapter": canonical,
                    "title": title,
                    "part": bool(PART.search(title)),
                    "needs_review": unresolved,
                    "source_file": doc.rel_path,
                    "start": heading.start(),
                    "end": end,
                }
            )
    if not sections:
        raise ValueError("No narrative chapters identified")
    groups = []
    for section in sections:
        key = (section["volume"], section["chapter"])
        if groups and section["part"] and groups[-1]["part"] and key == groups[-1]["key"]:
            groups[-1]["sections"].append(section)
        else:
            groups.append({"key": key, "part": section["part"], "sections": [section]})
    occurrences = Counter()
    notes = []
    for order, group in enumerate(groups, 1):
        key = group["key"]
        occurrences[key] += 1
        sections = group["sections"]
        spans = [{k: s[k] for k in ("source_file", "start", "end", "title")} for s in sections]
        notes.append(
            {
                "id": digest([key, occurrences[key]])[:24],
                "order": order,
                "title": f"{key[0]} · {key[1]}",
                "volume": key[0],
                "chapter": key[1],
                "sections": spans,
                "needs_review": any(s["needs_review"] for s in sections),
                "chars": sum(s["end"] - s["start"] for s in spans),
            }
        )
    sources = {d.rel_path: d.text for d in docs}
    for note in notes:
        note["basis"] = digest(
            [note["sections"], [sources[s["source_file"]][s["start"] : s["end"]] for s in note["sections"]]]
        )
    return {"source_basis": digest([(d.rel_path, d.text) for d in docs]), "notes": notes, "excluded": skipped}


def chunks(path: Path, project: dict, note: dict, limit: int = 6000) -> list[dict]:
    sources = {d.rel_path: d.text for d in discover_sources(path, project)}
    result = []
    for section in note["sections"]:
        text = sources[section["source_file"]]
        start = section["start"]
        while start < section["end"]:
            end = min(start + limit, section["end"])
            if end < section["end"]:
                boundary = text.rfind("\n", start + limit // 2, end)
                if boundary >= 0:
                    end = boundary + 1
            result.append(
                {
                    "source_file": section["source_file"],
                    "start": start,
                    "end": end,
                    "text": text[start:end],
                    "before_context": text[max(section["start"], start - 600) : start],
                    "after_context": text[end : min(section["end"], end + 400)],
                    "note_id": note["id"],
                }
            )
            start = end
    return result
