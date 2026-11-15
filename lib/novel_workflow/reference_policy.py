"""Reference-image intent is a director instruction, separate from image existence."""

from typing import Literal

from pydantic import Field

from lib.novel_workflow.models import StrictModel


class ReferencePolicy(StrictModel):
    controls: list[Literal["identity", "appearance", "environment", "lighting", "composition"]] = Field(
        min_length=1, max_length=5
    )
    excludes: str = Field(default="", max_length=1500)


def suggested(kind):
    return {"controls": ["environment", "lighting"] if kind == "scene" else ["identity", "appearance"], "excludes": ""}


def prompt(item):
    labels = {
        "identity": "身份",
        "appearance": "外观",
        "environment": "环境",
        "lighting": "光线",
        "composition": "构图",
    }
    policy = item.get("reference_policy") or suggested(item["kind"])
    scope = "、".join(labels[k] for k in policy["controls"])
    return f"{item['asset_code']} {item['name']}：仅参考{scope}；其余内容不作为生成依据。" + (
        f"禁止带入：{policy['excludes']}" if policy["excludes"] else ""
    )
