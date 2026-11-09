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
    variant: str = Field(
        default="",
        description="Character appearance variant explicitly supported by this quote (age/form/injury/costume); stable short label, empty if not established. Never infer from later plot.",
    )
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


class Moment(StrictModel):
    event_ids: list[str] = Field(min_length=1)
    scene: str = Field(min_length=1, description="爆点场面：触发、人物动作、冲突转折及可见结果")
    note_ids: list[str] = Field(min_length=1)
    dialogue_ids: list[str] = Field(min_length=1, description="该爆点所含原文台词ID，不能为空")
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


class SVTCandidate(StrictModel):
    existing_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=1500)
    reason: str = Field(min_length=1, max_length=1000)


class NoteAlternatives(StrictModel):
    note_id: str
    candidates: list[SVTCandidate] = Field(default_factory=list, max_length=5)


class SVTBatch(StrictModel):
    svts: list[SVTDraft] = Field(default_factory=list)
    supporting_event_ids: list[str] = Field(default_factory=list)
    alternatives: list[NoteAlternatives] = Field(default_factory=list)
    merge_suggestions: list[str] = Field(default_factory=list)


class Alias(StrictModel):
    name: str
    alias: str
    identity_scope: str = ""
    quote: str = Field(min_length=2)


class Relation(StrictModel):
    subject: str
    target: str
    relation: str
    previous: str = "未明确"
    trigger: str
    story_time: str = "未明确"
    quote: str = Field(min_length=2)


class Thread(StrictModel):
    kind: Literal["seed", "resolution"]
    description: str
    seed_id: str | None = None
    quote: str = Field(min_length=2)


class Highlight(StrictModel):
    kind: Literal["payoff", "growth", "fear", "ethical_conflict", "revelation", "tragedy", "hook"]
    description: str
    beneficiary: str
    intensity: Literal["small", "large"]
    reason: str
    visual: str
    quote: str = Field(min_length=2)


class ChapterSynthesis(StrictModel):
    summary: str = Field(min_length=1, max_length=3000)
    cause: str
    conflict: str
    action: str
    outcome: str
    hook: str
    evidence_ids: list[str] = Field(min_length=1)
    questions: list[str] = Field(default_factory=list)


class AdaptationAdvice(StrictModel):
    action: Literal["keep", "compress", "combine", "omit_candidate"]
    note_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    reason: str
    character_impact: str
    thread_impact: str
    dialogue_impact: str
    preserve: str


class ScopeReview(StrictModel):
    theme: str
    mainline: str
    advice: list[AdaptationAdvice] = Field(min_length=1)
    questions: list[str] = Field(default_factory=list)


class Reading(StrictModel):
    complete: bool
    summary: str
    assets: list[Mention] = Field(default_factory=list)
    changes: list[Change] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    aliases: list[Alias] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    threads: list[Thread] = Field(default_factory=list)
    highlights: list[Highlight] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class RangeConclusion(StrictModel):
    theme: str = Field(min_length=1, max_length=400)
    mainline: str = Field(min_length=1, max_length=2400)
    must_preserve: str = Field(min_length=1, max_length=1600)
    adaptation_risks: str = Field(min_length=1, max_length=1600)
    evidence_ids: list[str] = Field(min_length=1, max_length=40)
