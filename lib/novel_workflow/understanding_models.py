from typing import Literal

from pydantic import Field

from lib.novel_workflow.models import StrictModel


class Inquiry(StrictModel):
    queries: list[str] = Field(default_factory=list, max_length=6)
    questions: list[str] = Field(default_factory=list, max_length=12)


class Citation(StrictModel):
    fragment_id: str
    quote: str = Field(min_length=2, max_length=1200)


class Link(StrictModel):
    kind: Literal["identity", "thread_resolution", "state", "world_rule", "causal", "contradiction"]
    subject: str
    description: str
    status: Literal["supported", "uncertain"]
    story_time: str = "未明确"
    story_start_note_id: str | None = None
    story_end_note_id: str | None = None
    citations: list[Citation] = Field(min_length=2, max_length=8)


class Findings(StrictModel):
    links: list[Link] = Field(default_factory=list, max_length=12)
    unresolved: list[str] = Field(default_factory=list, max_length=12)
    next_queries: list[str] = Field(default_factory=list, max_length=3)
