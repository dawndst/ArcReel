"""Narrative scene → logical camera shot → generation segment (at most 15 s)."""

from pydantic import BaseModel, Field, model_validator

MAX_SEGMENT_SECONDS = 15


class ShotPlacement(BaseModel):
    scene_number: int | None = Field(default=None, ge=1, description="叙事场号；同一连续时空的一场戏共用场号，从1开始")
    shot_number: int | None = Field(
        default=None, ge=1, description="场内镜头号；切机位或切镜头才换号，长镜头的SEG共用镜头号"
    )
    segment_number: int | None = Field(
        default=None, ge=1, description="未拆段的镜头为null；长镜头拆段从1递增，同镜头保持相同场号与镜头号"
    )

    @model_validator(mode="after")
    def validate_placement(self):
        if self.scene_number is None and self.shot_number is None and self.segment_number is None:
            return self  # Existing unstructured scripts are not assigned invented scene boundaries.
        if self.scene_number is None or self.shot_number is None:
            raise ValueError("必须同时填写场号和镜头号")
        if getattr(self, "duration_seconds", 0) > MAX_SEGMENT_SECONDS:
            raise ValueError("一个生成片段不得超过15秒；请按动作和对白拆为同一镜头的SEG1、SEG2，不得截短或复制整段内容")
        return self


def validate_hierarchy(items) -> None:
    """Reject mixed, duplicate or interleaved parentage; camera cuts are not SEG boundaries."""
    if not any(item.scene_number is not None for item in items):
        return
    groups = {}
    closed = set()
    previous = None
    for item in items:
        if item.scene_number is None or item.shot_number is None:
            raise ValueError("剧本不能混用有层级和无层级的镜头，请补齐场号与镜头号")
        key = item.scene_number, item.shot_number
        if key != previous:
            if key in closed:
                raise ValueError("同一镜头的SEG必须连续排列，不可穿插其他镜头")
            if previous is not None:
                closed.add(previous)
            previous = key
        groups.setdefault(key, []).append(item.segment_number)
    for key, segments in groups.items():
        if segments == [None]:
            continue
        if segments != list(range(1, len(segments) + 1)):
            raise ValueError(f"第{key[0]}场第{key[1]}镜头的SEG必须从1连续编号，不能重复或缺段")


def placement_for_new_shot(items: list[dict], anchor: dict | None) -> dict:
    """A manual new row is a new logical shot in the anchor's scene, never an inferred SEG."""
    if not items:
        return {"scene_number": 1, "shot_number": 1, "segment_number": None}
    structured = [item for item in items if item.get("scene_number") is not None]
    if not structured:
        return {}
    scene = (anchor or structured[0]).get("scene_number") or structured[0]["scene_number"]
    return {
        "scene_number": scene,
        "shot_number": max(item.get("shot_number") or 0 for item in structured if item["scene_number"] == scene) + 1,
        "segment_number": None,
    }


def repair_removed_segments(original: dict, candidate: dict) -> None:
    """Deleting footage closes SEG numbering gaps without changing runtime IDs or other shots."""
    before, after = original.get("scenes", []), candidate.get("scenes", [])
    if not isinstance(before, list) or not isinstance(after, list):
        return
    before = [item for item in before if isinstance(item, dict)]
    after = [item for item in after if isinstance(item, dict)]
    remaining = {item.get("scene_id") for item in after}
    affected = {
        (item.get("scene_number"), item.get("shot_number"))
        for item in before
        if item.get("segment_number") is not None and item.get("scene_id") not in remaining
    }
    for key in affected:
        group = [item for item in after if (item.get("scene_number"), item.get("shot_number")) == key]
        for number, item in enumerate(group, 1):
            item["segment_number"] = number if len(group) > 1 else None


def starts_new_scene(previous: dict, current: dict) -> bool:
    if previous.get("scene_number") is not None and current.get("scene_number") is not None:
        return previous["scene_number"] != current["scene_number"]
    return bool(current.get("segment_break"))


def segment_durations(supported: list[int]) -> list[int]:
    allowed = [duration for duration in supported if duration <= MAX_SEGMENT_SECONDS]
    if not allowed:
        raise ValueError("当前视频模型没有15秒以内的可用时长，请更换模型")
    return allowed
