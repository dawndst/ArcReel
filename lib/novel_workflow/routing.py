"""Explicit workflow boundary: Note projects must never silently read the whole book."""


class WorkflowError(RuntimeError):
    """A user-actionable Note workflow prerequisite or stale source."""


def enabled(project):
    return project.get("content_mode") == "drama"


def reject_legacy(project):
    if enabled(project):
        raise WorkflowError(
            "当前使用 Note → SVT → 场镜 → 导演组集流程。请在小说工作台操作；旧的全书阅读不再调用；分集规划、原文切集和分集合并已删除。"
        )
