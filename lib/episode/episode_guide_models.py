"""Structured episode reading guide shared by planner and on-demand generation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class EpisodeGuide(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1)
    story_beats: list[str] = Field(min_length=1)
    character_changes: list[str] = Field(min_length=1)
    adaptation_value: str = Field(min_length=1)
    recommendation: Literal["keep", "compress", "merge"]
    recommendation_reason: str = Field(min_length=1)
    ending_hook: str = Field(min_length=1)
