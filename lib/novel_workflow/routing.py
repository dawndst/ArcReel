"""Explicit workflow boundary: Note projects must never silently read the whole book."""


class WorkflowError(RuntimeError):
    """A user-actionable Note workflow prerequisite or stale source."""


def enabled(project):
    return project.get("content_mode") == "drama"
