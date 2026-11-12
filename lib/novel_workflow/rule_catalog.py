"""Read-only catalogue of prompt rules, without credentials or task source material."""

from pathlib import Path

from lib.novel_understanding.store import digest
from lib.novel_workflow import settings, store
from lib.prompts.prompt_templates.builtin import builtin_templates

TITLES = {
    "quote_locations": ("重复引句定位", "根据原文候选上下文定位重复台词或短引句，不猜选位置、不改写台词"),
    "read_review": ("Note 抽取原文审核", "保存前核对信息性质、说话人、因果和状态变化；仅修订抽取结果，不改原文"),
    "understand_reconcile": ("跨章关联汇总核对", "核对同类跨章结论的重复和冲突，保留原文揭示边界"),
    "shot_execution": ("单镜执行方案修订", "原文对照、发声方式、关键资产、起止状态和剪辑切点；人工采用"),
    "selection_story": ("选镜后的观众理解检查", "只审阅实际选中音画，不借未选原文补脑；编导记录取舍"),
    "speaker_attribution": ("单镜对白说话人补判", "读取当前原文和相邻镜头，提供有证据的建议；采用后才填写说话人"),
    "condense": ("章节精编与原文回读", "逐段保留因果与原文索引，省略可追溯，待定内容保留原文"),
    "fidelity": ("事实、推测与对白归属", "保留认知边界、梦境与批注性质；无法确认的对白先留待确认"),
    "overview": ("故事设定：Note 归纳", "只汇总当前可用范围的精读成果，不重新读取全书"),
    "scope": ("未完结小说与可用章节", "限定阅读范围、保留待续线索，不要求读完全书"),
    "production": ("导演选镜后的生产约束", "保留导演选择、防止未选内容和未来设定混入制作"),
    "read": ("章节泛读与 Note 生成", "所选章节的梗概、人物、资产、事件、线索及原文依据"),
    "chapter": ("章节梗概", "有界归纳章节内容，包含项目摘要字数上限"),
    "understand": ("跨章理解与防剧透", "回查原文、揭示时序和未完结范围"),
    "svt": ("Note 主归属、SVT 备选与爆点", "一章一 Note；一个主归属＋多个备选；爆点场面＋台词＋来源 Note"),
    "review": ("改编建议", "保留、压缩、合并建议与依据"),
    "group": ("资料组合梗概", "仅管理资料，不决定成片集"),
    "shot_production": ("镜头设计与爆点关联", "补充镜头设计、原文事件与爆点关联，继承到原生制作流程"),
    "scenes": ("场与镜头规划", "从原文和主线事件生成场镜，供导演组集"),
}


def catalog(path, project):
    entries = []

    def add(key, title, purpose, category, content, source, location):
        entries.append(
            {
                "id": key,
                "title": title,
                "purpose": purpose,
                "category": category,
                "content": content,
                "source": source,
                "location": location,
                "version": digest(content)[:12],
            }
        )

    for name, (title, purpose) in TITLES.items():
        local = store.root(path) / "rules" / f"{name}.md"
        if local.is_symlink() or (local.exists() and not local.resolve().is_relative_to(path.resolve())):
            raise ValueError("项目规则文件不能是符号链接")
        if name == "read":
            from lib.novel_workflow.service import reading_rules

            text = reading_rules(path)
        elif name == "understand":
            from lib.novel_workflow.understanding import understanding_rules

            text = understanding_rules(path)
        else:
            text = settings.chapter_rule(path) if name == "chapter" else store.effective_rule(path, name)
        add(
            "novel/" + name,
            title,
            purpose,
            "novel",
            text,
            "project" if local.exists() else "default",
            f"novel_workflow/rules/{name}.md" if local.exists() else f"lib/novel_workflow/rules/{name}.md",
        )
    from lib.novel_understanding import store as legacy_store

    for name in legacy_store.RULE_NAMES:
        local = legacy_store.root(path) / "rules" / f"{name}.md"
        if local.is_symlink() or (local.exists() and not local.resolve().is_relative_to(path.resolve())):
            raise ValueError("项目规则文件不能是符号链接")
    for name, content in legacy_store.rules(path).items():
        local = legacy_store.root(path) / "rules" / f"{name}.md"
        add(
            "legacy/" + name,
            "原分集理解流程 / " + name,
            "旧理解流程规则；新版 Note 工作流不调用",
            "other",
            content,
            "project" if local.exists() else "default",
            f"novel_understanding/rules/{name}.md",
        )
    seen = set()
    for meta in builtin_templates.list_templates():
        content, partials = builtin_templates.read_source(meta.id)
        category = "other" if project.get("novel_workflow_enabled") and meta.stage == "episode_plan" else "production"
        add(
            "template/" + meta.id,
            meta.title,
            meta.description,
            category,
            content,
            "default",
            "templates/" + meta.id + ".md",
        )
        for part in partials:
            if part.name in seen:
                continue
            seen.add(part.name)
            add(
                "partial/" + part.name,
                part.name,
                "共享规则片段；引用方：" + "、".join(part.referenced_by),
                "partial",
                part.source,
                "default",
                part.name,
            )
    profile = Path(__file__).resolve().parents[2] / "agent_runtime_profile"
    mode = project.get("content_mode", "drama")
    local_persona = path / "CLAUDE.md"
    if local_persona.is_symlink() or (
        local_persona.exists() and not local_persona.resolve().is_relative_to(path.resolve())
    ):
        raise ValueError("项目规则文件不能是符号链接")
    for file in sorted(profile.glob("CLAUDE.*.md")):
        current_mode = file.name == f"CLAUDE.{mode}.md"
        active = current_mode and local_persona.is_file()
        add(
            "agent/" + file.name,
            "Agent 工作总则 / " + file.stem.removeprefix("CLAUDE."),
            "当前内容模式的 Agent 工作规则" if current_mode else "其他内容模式的 Agent 工作规则",
            "agent" if current_mode else "other",
            (local_persona if active else file).read_text(encoding="utf-8"),
            "project" if active else "default",
            "CLAUDE.md" if active else "agent_runtime_profile/" + file.name,
        )
    for file in sorted((profile / ".claude").rglob("*.md")):
        if "/scripts/" in file.as_posix():
            continue
        rel = file.relative_to(profile)
        variant = file.name.startswith("SKILL.") and file.name != "SKILL.md"
        current_variant = not variant or file.name == f"SKILL.{mode}.md"
        local_rel = rel.with_name("SKILL.md") if variant and current_variant else rel
        local = path / local_rel
        # Only regular in-project prompt documents are read; no env or settings files.
        active = (
            current_variant
            and local.is_file()
            and not local.is_symlink()
            and local.resolve().is_relative_to(path.resolve())
        )
        selected = local if active else file
        add(
            "agent/" + rel.as_posix(),
            file.parent.name + " / " + file.name,
            "Agent 技能或参考规则；仅在对应 Agent 流程调用时生效",
            "agent" if current_variant else "other",
            selected.read_text(encoding="utf-8"),
            "project" if active else "default",
            local_rel.as_posix() if active else rel.as_posix(),
        )
    return {"entries": entries, "read_only": True}
