"""Evidence-first contracts; model outputs cannot execute manual arrangement commands."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Mention(StrictModel):
    kind: Literal["character", "scene", "prop"]
    name: str = Field(min_length=1)
    identity_scope: str = Field(default="", description="Distinguish same-name entities; unknown stays unknown")
    description: str
    quote: str = Field(min_length=2)


class Change(StrictModel):
    character: str
    before: str
    after: str
    dimension: Literal["age", "form", "injury", "relationship", "knowledge", "emotion", "other"]
    story_time: str = "未明确"
    quote: str = Field(min_length=2)


class Dialogue(StrictModel):
    speaker: str
    quote: str = Field(min_length=2)
    value: str


class Event(StrictModel):
    title: str
    cause: str
    conflict: str
    action: str
    outcome: str
    characters: list[str] = Field(default_factory=list)
    open_thread: str = ""
    quote: str = Field(min_length=2)
    dialogues: list[Dialogue] = Field(default_factory=list)


class Reading(StrictModel):
    complete: bool
    summary: str
    assets: list[Mention] = Field(default_factory=list)
    changes: list[Change] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class Moment(StrictModel):
    event_ids: list[str] = Field(min_length=1)
    description: str
    reason: str


class SVTDraft(StrictModel):
    existing_id: str | None = None
    title: str
    summary: str
    event_ids: list[str] = Field(min_length=1)
    mainline_reason: str
    status: Literal["open", "closed"]
    climaxes: list[Moment] = Field(default_factory=list)
    payoffs: list[Moment] = Field(default_factory=list)
    dialogue_ids: list[str] = Field(default_factory=list)


class SVTBatch(StrictModel):
    svts: list[SVTDraft] = Field(default_factory=list)
    supporting_event_ids: list[str] = Field(default_factory=list)
    merge_suggestions: list[str] = Field(default_factory=list)
