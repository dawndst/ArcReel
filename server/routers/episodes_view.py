"""「分集」视图：整本源文按集分段的只读投影、``source/`` 里没有登记的文件的处置，整本源文文件的类型、
替换、编辑、删除与调序，以及按文件在服务之外的改动更新分集账本。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from lib.episode.episode_layout import build_episode_layout
from lib.episode.episode_source_commands import (
    EpisodeSourceError,
    adopt_source_file_as_episode,
    adopt_source_file_as_whole_source,
    set_whole_source_file_kind,
)
from lib.episode.source_file_changes import (
    MoveDirection,
    SourceFileChangeError,
    SourceFileChangeOutcome,
    accept_external_source_change,
    delete_whole_source_file,
    edit_whole_source_file,
    move_whole_source_file,
    replace_whole_source_file,
)
from lib.episode.source_kinds import SourceKind
from lib.infra.api_errors import ApiError, NotFoundError
from lib.infra.async_thread import run_sync_transaction
from lib.project.project_change_hints import project_change_source
from lib.project.project_manager import ProjectManager, get_project_manager
from server.dependencies import require_project_migration_ok
from server.i18n import Translator
from server.routers._episode_source_errors import episode_source_http_error
from server.routers._source_file_changes import (
    ensure_no_displaced_tasks,
    source_file_change_http_error,
    source_file_change_payload,
)
from server.routers._source_uploads import extract_uploaded_source_text

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/projects/{name}/episodes-view")
async def get_episodes_view(name: str, _t: Translator) -> dict[str, Any]:
    """整本源文按集分段、每集的体量与首尾句、``source/`` 里没有登记的文本文件、新的分集方案 ``replan``，
    以及在服务之外被改动过的文件 ``external_changes``。

    ``replan`` 是悬而未决的重新规划候选的摘要与逐集变化（见 :func:`lib.episode.episode_replan.replan_candidate_summary`），
    没有候选时为 null。``external_changes`` 按文件顺序列出 ``changed_outside`` 的文件：``impact`` 是按快照对齐算出的
    受影响集清单（含服务端成文的 ``text``），``revision`` 原样带给 ``accept-external`` 即确认；算不出清单时两者为
    null，``problem`` 是原因。
    """

    def _external_change(manager: ProjectManager, project: dict[str, Any], filename: str) -> dict[str, Any]:
        try:
            outcome = accept_external_source_change(manager, name, filename, dry_run=True)
        except SourceFileChangeError as exc:
            return {
                "source_file": f"source/{filename}",
                "impact": None,
                "revision": None,
                "problem": _t(f"source_file_change_{exc.code}"),
            }
        payload = source_file_change_payload(outcome, project, _t)
        return {
            "source_file": f"source/{filename}",
            "impact": payload["impact"],
            "revision": payload["revision"],
            "problem": None,
        }

    def _sync() -> dict[str, Any]:
        manager = get_project_manager()
        if not manager.project_exists(name):
            raise NotFoundError("project_not_found", name=name)
        project = manager.load_project(name)
        project_dir = manager.get_project_path(name)
        layout = build_episode_layout(project_dir, project)
        return {
            **asdict(layout),
            "replan": None,
            "external_changes": [
                _external_change(manager, project, file.name) for file in layout.files if file.changed_outside
            ],
        }

    try:
        return await run_sync_transaction(_sync)
    except (HTTPException, ApiError):
        raise
    except Exception as exc:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=_t("internal_server_error")) from exc


class AdoptSourceFileRequest(BaseModel):
    #: whole_source 加入整本源文末尾；episode 用作一集的原文。
    target: Literal["whole_source", "episode"]
    #: target=episode 时填给这一集（须是无原文的集）；缺省时在播出顺序末尾新建一集。
    episode: int | None = None


@router.post(
    "/projects/{name}/source-files/{filename}/adopt",
    dependencies=[Depends(require_project_migration_ok)],
)
async def adopt_source_file(name: str, filename: str, req: AdoptSourceFileRequest, _t: Translator) -> dict[str, Any]:
    """处置 ``source/`` 里没有登记的文件：加入整本源文，或用作一集的原文（原文件随即删除）。"""

    def _sync() -> dict[str, Any]:
        manager = get_project_manager()
        if not manager.project_exists(name):
            raise NotFoundError("project_not_found", name=name)
        with project_change_source("webui"):
            if req.target == "whole_source":
                adopt_source_file_as_whole_source(manager, name, filename)
                return {"success": True, "target": req.target, "path": f"source/{filename}"}
            episode = adopt_source_file_as_episode(manager, name, filename, req.episode)
        return {"success": True, "target": req.target, "episode": episode}

    try:
        return await run_sync_transaction(_sync)
    except EpisodeSourceError as exc:
        raise episode_source_http_error(exc, _t, episode=req.episode, filename=filename) from exc
    except (HTTPException, ApiError):
        raise
    except Exception as exc:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=_t("internal_server_error")) from exc


class SetSourceFileKindRequest(BaseModel):
    source_kind: SourceKind
    #: 已确认会让已开始制作的集的脚本规划判 stale。
    confirm: bool = False


@router.put(
    "/projects/{name}/source-files/{filename}/source-kind",
    dependencies=[Depends(require_project_migration_ok)],
)
async def set_source_file_kind(
    name: str, filename: str, req: SetSourceFileKindRequest, _t: Translator
) -> dict[str, Any]:
    """改整本源文文件的源文件类型（只对剧情演绎开放）；不改源文指纹，也不动分集账本。

    会让已开始制作的集的脚本规划判 stale 而 ``confirm`` 为 false 时不写入，返回 ``needs_confirmation``
    与这些集的集 ID（``affected_episodes``）。
    """

    def _sync() -> dict[str, Any]:
        manager = get_project_manager()
        if not manager.project_exists(name):
            raise NotFoundError("project_not_found", name=name)
        with project_change_source("webui"):
            change = set_whole_source_file_kind(manager, name, filename, req.source_kind, confirm=req.confirm)
        return {
            "success": True,
            "applied": change.applied,
            "needs_confirmation": change.changed and not change.applied,
            "affected_episodes": change.affected_episodes,
        }

    try:
        return await run_sync_transaction(_sync)
    except EpisodeSourceError as exc:
        raise episode_source_http_error(exc, _t, filename=filename) from exc
    except (HTTPException, ApiError):
        raise
    except Exception as exc:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=_t("internal_server_error")) from exc


# ---------------------------------------------------------------------------
# 整本源文文件的替换、编辑、删除与调序
# ---------------------------------------------------------------------------


class _SourceFileChangeBase(BaseModel):
    #: 创作者确认过的受影响集清单的版本；缺省或与锁内重算的不一致时只返回清单，不写入。
    revision: str | None = None


class EditSourceFileRequest(_SourceFileChangeBase):
    text: str


class MoveSourceFileRequest(_SourceFileChangeBase):
    direction: MoveDirection


class DeleteSourceFileRequest(_SourceFileChangeBase):
    pass


async def _run_source_file_change(
    name: str,
    _t: Translator,
    revision: str | None,
    command: Callable[[ProjectManager, bool], SourceFileChangeOutcome],
) -> dict[str, Any]:
    """``command(manager, dry_run)`` 跑一个整本源文文件改动命令，``revision`` 已经传给了它。"""

    def _manager() -> ProjectManager:
        manager = get_project_manager()
        if not manager.project_exists(name):
            raise NotFoundError("project_not_found", name=name)
        return manager

    def _sync() -> dict[str, Any]:
        manager = _manager()
        project = manager.load_project(name)
        with project_change_source("webui"):
            outcome = command(manager, False)
        return source_file_change_payload(outcome, project, _t)

    try:
        await ensure_no_displaced_tasks(name, revision, lambda: command(_manager(), True), _t)
        return await run_sync_transaction(_sync)
    except SourceFileChangeError as exc:
        raise source_file_change_http_error(exc, _t) from exc
    except (HTTPException, ApiError):
        raise
    except Exception as exc:
        logger.exception("请求处理失败")
        raise HTTPException(status_code=500, detail=_t("internal_server_error")) from exc


@router.put(
    "/projects/{name}/source-files/{filename}/text",
    dependencies=[Depends(require_project_migration_ok)],
)
async def edit_source_file(name: str, filename: str, req: EditSourceFileRequest, _t: Translator) -> dict[str, Any]:
    """编辑整本源文文件的全文，按改动前后的对齐重映射触及它的切出集。

    没有受影响的集时直接执行，返回 ``status=applied``；有受影响的集而 ``revision`` 缺省或已过时时不写入，
    返回 ``status=confirmation_required``、按类分组的受影响集清单（含服务端成文的 ``impact.text``）与 ``revision``。
    要移除或转为无原文的集有排队或执行中的任务时返回 409，不写入。
    """
    return await _run_source_file_change(
        name,
        _t,
        req.revision,
        lambda pm, dry_run: edit_whole_source_file(
            pm, name, filename, req.text, revision=req.revision, dry_run=dry_run
        ),
    )


@router.post(
    "/projects/{name}/source-files/{filename}/replace",
    dependencies=[Depends(require_project_migration_ok)],
)
async def replace_source_file(
    name: str,
    filename: str,
    _t: Translator,
    file: UploadFile = File(...),
    source_kind: Annotated[SourceKind | None, Form()] = None,
    revision: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """用上传的文件替换整本源文文件：保留位置与文件名，类型缺省时不变。

    没有受影响的集时直接执行，返回 ``status=applied``；有受影响的集而 ``revision`` 缺省或已过时时不写入，
    返回 ``status=confirmation_required``、按类分组的受影响集清单（含服务端成文的 ``impact.text``）与 ``revision``。
    要移除或转为无原文的集有排队或执行中的任务时返回 409，不写入。
    """
    text = await asyncio.to_thread(extract_uploaded_source_text, file, _t)
    return await _run_source_file_change(
        name,
        _t,
        revision,
        lambda pm, dry_run: replace_whole_source_file(
            pm, name, filename, text, source_kind=source_kind, revision=revision, dry_run=dry_run
        ),
    )


@router.post(
    "/projects/{name}/source-files/{filename}/move",
    dependencies=[Depends(require_project_migration_ok)],
)
async def move_source_file(name: str, filename: str, req: MoveSourceFileRequest, _t: Translator) -> dict[str, Any]:
    """把整本源文文件上移或下移一位，其中的切出集整块跟着走。

    没有受影响的集时直接执行，返回 ``status=applied``；有受影响的集而 ``revision`` 缺省或已过时时不写入，
    返回 ``status=confirmation_required``、按类分组的受影响集清单（含服务端成文的 ``impact.text``）与 ``revision``。
    要移除或转为无原文的集有排队或执行中的任务时返回 409，不写入。
    """
    return await _run_source_file_change(
        name,
        _t,
        req.revision,
        lambda pm, dry_run: move_whole_source_file(
            pm, name, filename, direction=req.direction, revision=req.revision, dry_run=dry_run
        ),
    )


class AcceptExternalChangeRequest(_SourceFileChangeBase):
    pass


@router.post(
    "/projects/{name}/source-files/{filename}/accept-external",
    dependencies=[Depends(require_project_migration_ok)],
)
async def accept_external_change(
    name: str, filename: str, req: AcceptExternalChangeRequest, _t: Translator
) -> dict[str, Any]:
    """按文件在服务之外的改动更新分集账本：以快照为旧文本、当前文本为新文本对齐，重映射触及它的切出集。

    没有受影响的集时直接执行，返回 ``status=applied``；有受影响的集而 ``revision`` 缺省或已过时时不写入，
    返回 ``status=confirmation_required``、按类分组的受影响集清单（含服务端成文的 ``impact.text``）与 ``revision``。
    文件没有改动过、或里面有切出集却没有快照时返回 409。要移除或转为无原文的集有排队或执行中的任务时返回 409，不写入。
    """
    return await _run_source_file_change(
        name,
        _t,
        req.revision,
        lambda pm, dry_run: accept_external_source_change(pm, name, filename, revision=req.revision, dry_run=dry_run),
    )


@router.post(
    "/projects/{name}/source-files/{filename}/delete",
    dependencies=[Depends(require_project_migration_ok)],
)
async def delete_whole_source(name: str, filename: str, req: DeleteSourceFileRequest, _t: Translator) -> dict[str, Any]:
    """删除整本源文文件，等同于删掉它的全部文字。

    没有受影响的集时直接执行，返回 ``status=applied``；有受影响的集而 ``revision`` 缺省或已过时时不写入，
    返回 ``status=confirmation_required``、按类分组的受影响集清单（含服务端成文的 ``impact.text``）与 ``revision``。
    要移除或转为无原文的集有排队或执行中的任务时返回 409，不写入。
    """
    return await _run_source_file_change(
        name,
        _t,
        req.revision,
        lambda pm, dry_run: delete_whole_source_file(pm, name, filename, revision=req.revision, dry_run=dry_run),
    )


_guide_running: set[tuple[str, int]] = set()


@router.get("/projects/{name}/episodes/{episode}/guide")
async def get_episode_guide(name: str, episode: int):
    from lib.episode import episode_guide

    def read():
        manager = get_project_manager()
        path = manager.get_project_path(name)
        data = episode_guide.snapshot(path, manager.load_project(name), episode)
        return {**episode_guide.cached(path, data), "running": (name, episode) in _guide_running}

    try:
        return await asyncio.to_thread(read)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/projects/{name}/episodes/{episode}/guide", dependencies=[Depends(require_project_migration_ok)])
async def generate_episode_guide(name: str, episode: int):
    from lib.episode import episode_guide

    def read():
        manager = get_project_manager()
        path = manager.get_project_path(name)
        return path, episode_guide.snapshot(path, manager.load_project(name), episode)

    key = (name, episode)
    if key in _guide_running:
        raise HTTPException(status_code=409, detail="Episode guide generation is already running")
    _guide_running.add(key)
    try:
        path, data = await asyncio.to_thread(read)
        guide = await episode_guide.generate(path, data)

        def commit():
            from lib.artifacts.formal_write import project_metadata_lock

            with project_metadata_lock(path):
                _, current = read()
                if current["basis"] != data["basis"]:
                    raise HTTPException(
                        status_code=409, detail="Episode source or guide rules changed; regenerate the guide"
                    )
                episode_guide.save(path, data, guide)
                return episode_guide.cached(path, data)

        return await run_sync_transaction(commit)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    finally:
        _guide_running.discard(key)
