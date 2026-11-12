"""Unassigned narrative scenes and logical shots, independent of episodes."""

from typing import Literal

from pydantic import Field, model_validator

from lib.novel_workflow.models import StrictModel
from lib.speech.delivery import LibraryDelivery


class LibraryUtterance(StrictModel):
    """Unresolved attribution is valid in the library, never in a production script."""

    delivery: LibraryDelivery = Field(
        default="unclassified",
        description="on_screen画内对白；off_screen角色画外发声；inner内心独白，不张口；narration无角色旁白。必须按原文确认，不因已知说话人就认为其入画。",
    )
    origin: Literal["source", "adaptation"] = "source"
    basis_quote: str = Field(default="", max_length=3000, description="改编对白引用原文依据，不能把改编文字冒充原文")
    kind: Literal["dialogue", "voiceover"]
    speaker: str | None = None
    text: str = Field(min_length=1)

    @model_validator(mode="after")
    def normalize(self):
        if self.kind == "voiceover" and self.delivery == "unclassified":
            self.delivery = "narration"
        self.speaker = self.speaker.strip() if self.speaker and self.speaker.strip() else None
        if self.delivery != "unclassified" and ((self.kind == "voiceover") != (self.delivery == "narration")):
            raise ValueError("发声方式与角色对白/旁白不一致")
        if self.kind == "voiceover" and self.speaker:
            raise ValueError("旁白不能携带角色；角色画外音仍属于 dialogue")
        return self


class AssetState(StrictModel):
    kind: Literal["character", "scene", "prop"]
    name: str = Field(min_length=1, max_length=200)
    visibility: Literal["visible", "hidden", "off_screen"] = "visible"
    start: str = Field(default="", max_length=1500)
    end: str = Field(default="", max_length=1500)
    attachment: str = Field(default="", max_length=500, description="持握、佩戴、骑乘和组件关系；不适用可空")


class Segment(StrictModel):
    start_frame: str = Field(
        default="", max_length=2000, description="本片段可见的起始画面与站位；不得靠无法看见的心理说明代替"
    )
    end_frame: str = Field(default="", max_length=2000, description="本片段结束画面，下一SEG须继承的状态")
    asset_states: list[AssetState] = Field(default_factory=list, max_length=50)
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
