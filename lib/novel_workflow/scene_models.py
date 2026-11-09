"""Unassigned narrative scenes and logical shots, independent of episodes."""

from pydantic import Field

from lib.novel_workflow.models import StrictModel
from lib.script.script_models import Utterance


class Segment(StrictModel):
    duration_seconds: int = Field(ge=1, le=15)
    scene_description: str = Field(min_length=1, max_length=4000)
    characters_in_scene: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    utterances: list[Utterance] = Field(default_factory=list)


class LibraryShot(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    quote: str = Field(min_length=2, max_length=3000)
    segments: list[Segment] = Field(min_length=1, max_length=20)


class LibraryScene(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    location: str = Field(max_length=200)
    time: str = Field(max_length=200)
    purpose: str = Field(max_length=1000)
    shots: list[LibraryShot] = Field(min_length=1, max_length=40)


class SceneBatch(StrictModel):
    scenes: list[LibraryScene] = Field(default_factory=list, max_length=30)
    skipped_reason: str = Field(default="", max_length=1000)
