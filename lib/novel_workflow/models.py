"""Evidence-first contracts; model outputs cannot execute manual arrangement commands."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidencedClaim(StrictModel):
    claim_type: Literal["fact", "statement", "inference", "vision", "adaptation", "unverified"] = Field(
        default="unverified",
        description="fact=正文明确事实；statement=人物说法；inference=推测；vision=梦境或幻象；adaptation=改编建议；unverified=未判定。引用存在不等于结论成立。",
    )
    perspective: str = Field(default="", description="谁说、谁猜、谁梦见；事实可为空。不得将角色认知提升为客观事实。")
    source_kind: Literal["narrative", "annotation", "unknown"] = Field(
        default="unknown", description="正文、读者/译者批注、未判定；批注不作剧情事实"
    )

    @model_validator(mode="after")
    def retain_perspective(self):
        if self.claim_type in {"statement", "inference", "vision"} and not self.perspective.strip():
            raise ValueError("人物说法、推测或梦境必须标明认知主体 perspective；未知时写明未明确，不得默认客观事实")
        if self.source_kind == "annotation" and self.claim_type == "fact":
            raise ValueError("读者或译者批注不能标为正文事实")
        return self


class Mention(EvidencedClaim):
    kind: Literal["character", "scene", "prop"]
    name: str = Field(min_length=1)
    identity_scope: str = Field(default="", description="Distinguish same-name entities; unknown stays unknown")
    variant: str = Field(
        default="",
        description="Character appearance variant explicitly supported by this quote (age/form/injury/costume); stable short label, empty if not established. Never infer from later plot.",
    )
    description: str
    quote: str = Field(min_length=2)


class Change(EvidencedClaim):
    character: str
    before: str
    after: str
    dimension: Literal["age", "form", "injury", "relationship", "knowledge", "emotion", "other"]
    story_time: str = "未明确"
    quote: str = Field(min_length=2)


class Dialogue(EvidencedClaim):
    speaker: str
    quote: str = Field(min_length=2)
    value: str


class Event(EvidencedClaim):
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


class Alias(EvidencedClaim):
    name: str
    alias: str
    identity_scope: str = ""
    quote: str = Field(min_length=2)


class Relation(EvidencedClaim):
    record_kind: Literal["existing", "established", "changed", "unclassified"] = Field(
        default="unclassified",
        description="existing=本章记录的既有关系；established=剧情中明确新建立关系；changed=已知此前关系发生转变；unclassified=依据不足。亲属关系首次被记录不等于此刻才成为亲属。",
    )
    subject: str
    target: str
    relation: str
    previous: str = "未明确"
    trigger: str
    story_time: str = "未明确"
    quote: str = Field(min_length=2)


class Thread(EvidencedClaim):
    kind: Literal["seed", "resolution"]
    description: str
    seed_id: str | None = None
    quote: str = Field(min_length=2)


class Highlight(EvidencedClaim):
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


class ReadingQuestion(StrictModel):
    text: str = Field(min_length=1)
    kind: Literal["plot_unrevealed", "extraction_check", "unclassified"] = Field(
        description="plot_unrevealed=剧情尚未揭示的悬念；extraction_check=身份指代或抽取结论需要核实；unclassified=无法可靠分类。不把剧情悬念当作生成错误。"
    )


class Reading(StrictModel):
    reading_questions: list[ReadingQuestion] = Field(
        default_factory=list,
        description="阅读疑问按剧情待揭示、抽取待核实分类；不确定时unclassified。与场镜制作审核阻断问题不同。",
    )
    complete: bool
    summary: str
    assets: list[Mention] = Field(default_factory=list)
    changes: list[Change] = Field(default_factory=list)
    events: list[Event] = Field(default_factory=list)
    aliases: list[Alias] = Field(default_factory=list)
    relations: list[Relation] = Field(
        default_factory=list,
        description="只记录对冲突、信任、权力、效忠或身份揭示有作用的关系及其变化。老师是老师、女儿是女儿等无触发事件的基础身份不重复列出；亲属身份揭晓或新建立关系须保留。",
    )
    threads: list[Thread] = Field(default_factory=list)
    highlights: list[Highlight] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)


class RangeConclusion(StrictModel):
    theme: str = Field(min_length=1, max_length=400)
    mainline: str = Field(min_length=1, max_length=2400)
    must_preserve: str = Field(min_length=1, max_length=1600)
    adaptation_risks: str = Field(min_length=1, max_length=1600)
    evidence_ids: list[str] = Field(min_length=1, max_length=40)
