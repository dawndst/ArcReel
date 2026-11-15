"""Project shot performance phases into execution segments without changing source drafts."""

from copy import deepcopy


def groups(segments):
    if len(segments) > 1 and sum(s["duration_seconds"] for s in segments) <= 15:
        return [list(range(len(segments)))]
    return [[i] for i in range(len(segments))]


def merge(segments):
    if len(segments) == 1:
        return deepcopy(segments[0])
    result = deepcopy(segments[0])
    result["duration_seconds"] = sum(s["duration_seconds"] for s in segments)
    result["scene_description"] = "\n".join(s["scene_description"] for s in segments)
    result["utterances"] = [deepcopy(u) for s in segments for u in s.get("utterances", [])]
    for field in ("characters_in_scene", "scenes", "props"):
        result[field] = list(dict.fromkeys(n for s in segments for n in s.get(field, [])))
    if "end_frame" in segments[-1]:
        result["end_frame"] = segments[-1]["end_frame"]
    if any(s.get("asset_states") for s in segments):
        result["asset_states"] = [deepcopy(state) for s in segments for state in s.get("asset_states", [])]
    return result


def project(segments):
    return [merge([segments[i] for i in indexes]) for indexes in groups(segments)]
