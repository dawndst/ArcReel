from typing import Literal

from pydantic import Field

from lib.novel_workflow.models import EvidencedClaim, StrictModel


class Inquiry(StrictModel):
    queries: list[str] = Field(default_factory=list, max_length=6)
    questions: list[str] = Field(default_factory=list, max_length=12)


class Citation(StrictModel):
    fragment_id: str
    quote: str = Field(
        min_length=2,
        max_length=1200,
        description="从该 fragment 复制一条短的、连续的原句，优先 20–120 字。不能新增省略号、省掉句间正文或拼接多处文字；需要多处证据时拆成多个 citations。推理放在 description，不写进 quote。",
    )


class Link(EvidencedClaim):
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
