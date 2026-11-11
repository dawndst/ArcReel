"""Unassigned narrative scenes and logical shots, independent of episodes."""

from typing import Literal

from pydantic import Field, model_validator

from lib.novel_workflow.models import StrictModel


class LibraryUtterance(StrictModel):
    """Unresolved attribution is valid in the library, never in a production script."""

    kind: Literal["dialogue", "voiceover"]
    speaker: str | None = None
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize(self):
        self.speaker = self.speaker.strip() if self.speaker and self.speaker.strip() else None
        if self.kind == "voiceover" and self.speaker:
            raise ValueError("旁白不能携带角色；角色画外音仍属于 dialogue")
        return self


class Segment(StrictModel):
    duration_seconds: int = Field(ge=1, le=15)
    scene_description: str = Field(min_length=1, max_length=4000)
    characters_in_scene: list[str] = Field(default_factory=list)
    scenes: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    utterances: list[LibraryUtterance] = Field(default_factory=list)


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
