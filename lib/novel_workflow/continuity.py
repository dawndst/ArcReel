"""Compare explicit state at actual edit boundaries, without inventing spatial facts."""

from lib.novel_workflow.common import digest

STATE_FIELDS = ("position", "holder", "gaze")


def boundaries(shots):
    result = []
    previous = None
    for shot in shots:
        for index, segment in enumerate(shot["segments"]):
            if previous:
                left, left_index, end = previous
                same_scene = left["scene_id"] == shot["scene_id"]
                comparisons = []
                old = {(s["kind"], s["name"]): s for s in end.get("asset_states", [])}
                for current in segment.get("asset_states", []):
                    prior = old.get((current["kind"], current["name"]))
                    if not prior or not same_scene:
                        continue
                    for field in STATE_FIELDS:
                        before = prior.get("end_" + field, "").strip()
                        after = current.get("start_" + field, "").strip()
                        if before or after:
                            comparisons.append(
                                {
                                    "asset": current["name"],
                                    "field": field,
                                    "before": before,
                                    "after": after,
                                    "status": "missing"
                                    if not before or not after
                                    else "match"
                                    if before == after
                                    else "review",
                                }
                            )
                identity = digest([left["id"], left_index, shot["id"], index, end, segment])[:24]
                result.append(
                    {
                        "id": identity,
                        "from_shot": left["id"],
                        "from_segment": left_index,
                        "to_shot": shot["id"],
                        "to_segment": index,
                        "same_scene": same_scene,
                        "end_frame": end.get("end_frame", ""),
                        "start_frame": segment.get("start_frame", ""),
                        "states": comparisons,
                        "status": "scene_change"
                        if not same_scene
                        else "review"
                        if any(c["status"] != "match" for c in comparisons)
                        else "recorded"
                        if comparisons
                        else "unrecorded",
                    }
                )
            previous = shot, index, segment
    return result


def issues(boundary_list):
    return [
        {
            "id": b["id"],
            "code": "continuity_boundary",
            "decision_key": "continuity:" + b["id"],
            "hard": False,
            "shot_id": b["to_shot"],
            "segment": b["to_segment"],
            "details": b,
        }
        for b in boundary_list
        if b["status"] == "review"
    ]


def decision_key(issue):
    return issue.get("decision_key", issue["code"])
