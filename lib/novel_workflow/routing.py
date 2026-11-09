"""Explicit workflow boundary: Note projects must never silently read the whole book."""


class WorkflowError(RuntimeError):
    """A user-actionable Note workflow prerequisite or stale source."""


def enabled(project):
    return project.get("content_mode") == "drama" and project.get("novel_workflow_enabled") is True


def reject_legacy(project):
    if enabled(project):
        raise WorkflowError(
            "当前使用 Note → SVT → 场镜 → 导演组集流程。请在小说工作台操作；旧的全书阅读、分集切分和分集合并入口已停用。"
        )
