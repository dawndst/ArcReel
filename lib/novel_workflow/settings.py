"""Independent controls for chapter summaries and cross-chapter understanding."""

from lib.artifacts.formal_write import project_metadata_lock
from lib.novel_workflow import store
from lib.novel_workflow.storage import load_json

DEFAULTS = {
    "summary_max_chars": 1200,
    "understanding_enabled": True,
    "delivery_checks_enabled": True,
    "craft_checks_enabled": True,
    "conclusions_enabled": True,
    "max_model_calls": 100,
}


def get(path):
    target = store.root(path) / "settings.json"
    return {**DEFAULTS, **(load_json(target) if target.exists() else {})}


def update(path, values):
    limit = values.get("summary_max_chars", get(path)["summary_max_chars"])
    if not isinstance(limit, int) or isinstance(limit, bool) or not 400 <= limit <= 3000:
        raise ValueError("Summary limit must be between 400 and 3000 characters")
    calls = values.get("max_model_calls", get(path)["max_model_calls"])
    if not isinstance(calls, int) or isinstance(calls, bool) or not 1 <= calls <= 500:
        raise ValueError("Model generation limit must be between 1 and 500")
    with project_metadata_lock(path):
        result = {**get(path), **values}
        store.write(store.root(path) / "settings.json", result)
    return result


def chapter_rule(path):
    limit = get(path)["summary_max_chars"]
    return (
        store.effective_rule(path, "chapter")
        + f"\n整章摘要 summary 上限为 {limit} 个字符。按信息密度使用篇幅，长章尽量保留完整因果、转折、人物变化和关键线索；短章不凑字数。"
    )
