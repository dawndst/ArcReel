"""Persisted reading evidence and model-response contracts.

Reader reveal positions are derived from verified source quotations, never from
model-supplied character offsets. Story time and character knowledge remain
separate annotations rather than substitutes for the reader's reveal position.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FactCategory = Literal["world", "identity", "relationship", "appearance", "state", "event", "setup", "payoff"]
AssertionKind = Literal["established", "character_claim", "inference", "uncertain"]
NarrativeFunction = Literal[
    "conflict",
    "character_change",
    "relationship_change",
    "causal_bridge",
    "setup",
    "payoff",
    "atmosphere",
    "repetition",
]


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source_file: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote: str


class FactDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=100)
    related_entities: list[str] = Field(default_factory=list, max_length=12)
    category: FactCategory
    statement: str = Field(min_length=1, max_length=600)
    assertion: AssertionKind = "established"
    evidence_quote: str = Field(min_length=10, max_length=300)
    story_time: str = Field(default="", max_length=200)
    known_by: list[str] = Field(default_factory=list, max_length=20)
    narrative_functions: list[NarrativeFunction] = Field(default_factory=list)


class ReadingDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=1500)
    facts: list[FactDraft] = Field(max_length=64)
    open_questions: list[str] = Field(default_factory=list, max_length=12)


class StoryFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    subject: str
    related_entities: list[str]
    category: FactCategory
    statement: str
    assertion: AssertionKind
    evidence: Evidence
    story_time: str
    known_by: list[str]
    narrative_functions: list[NarrativeFunction]


class ReadChunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
    index: int
    source_file: str
    start: int
    end: int
    source_digest: str
    summary: str
    facts: list[StoryFact]
    open_questions: list[str]
    reading_summaries: list[str] = Field(default_factory=list)


class BookSynthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    synopsis: str = Field(max_length=2500)
    genre: str = Field(max_length=200)
    theme: str = Field(max_length=500)
    world_setting: str = Field(max_length=2500)
    adaptation_guidance: list[str] = Field(default_factory=list, max_length=20)
    unresolved_questions: list[str] = Field(default_factory=list, max_length=20)


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item_id: str
    kind: Literal["premature_reveal", "character_knowledge", "canon_conflict", "state_mismatch", "unnecessary_episode"]
    offending_text: str = Field(min_length=1, max_length=800)
    fact_ids: list[str] = Field(default_factory=list, max_length=8)
    explanation: str = Field(max_length=1000)


class ReviewDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=24)


class EditorialDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["keep", "revise", "merge_next"]
    reason: str = Field(max_length=1500)
    must_film: list[str] = Field(max_length=20)
    compress: list[str] = Field(max_length=20)
    omit: list[str] = Field(max_length=20)
    preserve_setup: list[str] = Field(max_length=20)
    evidence_ids: list[str] = Field(min_length=1, max_length=20)
    title: str = Field(min_length=1, max_length=200)
    story_beats: list[str] = Field(min_length=1, max_length=30)
    hook: str = Field(max_length=600)
