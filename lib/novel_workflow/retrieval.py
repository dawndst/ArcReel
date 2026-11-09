"""Local retrieval within the currently available chapters, including unread Notes in that range."""

from __future__ import annotations

import math
import re
from collections import Counter

from lib.episode.episode_sources import discover_sources
from lib.infra.json_io import load_json
from lib.novel_understanding.store import digest
from lib.novel_workflow import store


def tokens(text):
    text = text.lower()
    result = re.findall(r"[a-z0-9_]+", text)
    for word in re.findall(r"[\u3400-\u9fff]+", text):
        result.extend(word[i : i + 2] for i in range(len(word) - 1))
        if len(word) == 1:
            result.append(word)
    return result


def index(path, project, notebook):
    from lib.novel_workflow import scope

    allowed = scope.available_ids(path, notebook)
    key = digest([notebook["source_basis"], sorted(allowed)])
    target = store.root(path) / "source_index" / f"{key}-v2.json"
    if target.exists():
        return load_json(target)
    sources = {d.rel_path: d.text for d in discover_sources(path, project)}
    fragments = []
    for note in notebook["notes"]:
        if note["id"] not in allowed:
            continue
        for section in note["sections"]:
            start = section["start"]
            while start < section["end"]:
                end = min(start + 1400, section["end"])
                text = sources[section["source_file"]][start:end]
                fragments.append(
                    {
                        "id": digest([section["source_file"], start, end, text])[:24],
                        "note_id": note["id"],
                        "order": note["order"],
                        "title": note["title"],
                        "source_file": section["source_file"],
                        "start": start,
                        "end": end,
                        "text": text,
                    }
                )
                if end == section["end"]:
                    break
                start = end - 160
    value = {"source_basis": notebook["source_basis"], "fragments": fragments}
    store.write(target, value)
    return value


def search(corpus, queries, *, exclude=(), limit=8):
    query_tokens = set(tokens(" ".join(queries)))
    if not query_tokens:
        return []
    documents = corpus["fragments"]
    counts = [Counter(tokens(d["text"])) for d in documents]
    frequencies = Counter(t for count in counts for t in query_tokens if t in count)
    scored = []
    for document, count in zip(documents, counts, strict=True):
        if document["id"] in exclude:
            continue
        length = sum(count.values())
        score = sum(
            math.log(1 + len(documents) / (1 + frequencies[t]))
            * count[t]
            / (count[t] + 1.2 * (0.25 + 0.75 * length / 900))
            for t in query_tokens
            if count[t]
        )
        score += sum(4 for q in queries if len(q.strip()) >= 2 and q.strip() in document["text"])
        if score > 0:
            scored.append((score, document))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    selected = []
    per_note = Counter()
    for _score, document in scored:
        if per_note[document["note_id"]] >= 2:
            continue
        selected.append(document)
        per_note[document["note_id"]] += 1
        if len(selected) == limit:
            break
    return selected


def anchors(corpus, records):
    """Use the actual source quote with a small surrounding window, not an LLM summary."""
    selected = {}
    for record in records:
        ev = record["evidence"]
        found = next(
            (
                f
                for f in corpus["fragments"]
                if f["note_id"] == ev["note_id"] and f["start"] <= ev["start"] and f["end"] >= ev["end"]
            ),
            None,
        )
        if found:
            start = max(found["start"], ev["start"] - 120)
            end = min(found["end"], ev["end"] + 120)
            fragment = {
                **found,
                "start": start,
                "end": end,
                "text": found["text"][start - found["start"] : end - found["start"]],
            }
            fragment["id"] = digest([found["id"], start, end])[:24]
            selected[fragment["id"]] = fragment
        else:
            # A long quote may cross index windows. It was validated at extraction time.
            original = next((f for f in corpus["fragments"] if f["note_id"] == ev["note_id"]), None)
            if original:
                fragment = {
                    **original,
                    "source_file": ev["source_file"],
                    "start": ev["start"],
                    "end": ev["end"],
                    "text": ev["quote"],
                }
                fragment["id"] = digest([ev["source_file"], ev["start"], ev["quote"]])[:24]
                selected[fragment["id"]] = fragment
    return list(selected.values())
