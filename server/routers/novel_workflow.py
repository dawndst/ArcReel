"""Chapter-first workflow endpoints; manual arrangement is separate from AI jobs."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.infra.async_thread import run_sync_transaction
from lib.novel_workflow import chapters, store
from lib.project.project_manager import get_project_manager
from server.agent_toolset.envelope import json_value
from server.auth import CurrentUser
from server.dependencies import require_project_migration_ok
from server.routers.episode_planning import _context
from server.tool_runtime import submit_note_workflow

router = APIRouter()


class SourceRequest(BaseModel):
    source_basis: str


class ReadingRequest(SourceRequest):
    action: Literal["read", "svt", "review", "understand"]
    note_ids: list[str] = Field(min_length=1, max_length=10000)


class GroupRequest(SourceRequest):
    note_ids: list[str] = Field(min_length=1, max_length=10000)
    title: str = Field(default="", max_length=200)


async def invoke(name, operation):
    def run():
        manager = get_project_manager()
        return operation(manager.get_project_path(name), manager.load_project(name))

    try:
        return await run_sync_transaction(run)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/projects/{name}/novel-workflow")
async def get_workflow(name: str):
    return await invoke(name, store.view)


@router.get("/projects/{name}/novel-workflow/preview")
async def preview(name: str):
    return await invoke(name, chapters.index)


@router.post("/projects/{name}/novel-workflow/initialize", dependencies=[Depends(require_project_migration_ok)])
async def initialize(name: str, req: SourceRequest):
    return await invoke(name, lambda path, project: store.initialize(path, project, req.source_basis))


@router.post("/projects/{name}/novel-workflow/run", dependencies=[Depends(require_project_migration_ok)])
async def run_workflow(name: str, req: ReadingRequest, user: CurrentUser):
    def validate(path, project):
        if project.get("novel_workflow_enabled") is not True:
            raise ValueError("Enable chapter Note workflow in project settings first")
        return store.require_current(path, project, req.source_basis)

    await invoke(name, validate)
    scope, caller, services = _context(name, user.id)
    result = await submit_note_workflow(scope, caller, services, req.model_dump())
    if result.problem:
        raise HTTPException(status_code=409, detail=result.problem.detail)
    return {"batch": json_value(result.value)}


@router.post("/projects/{name}/novel-workflow/groups", dependencies=[Depends(require_project_migration_ok)])
async def create_group(name: str, req: GroupRequest):
    return await invoke(
        name, lambda path, project: store.group_notes(path, project, req.note_ids, req.title, req.source_basis)
    )


@router.delete(
    "/projects/{name}/novel-workflow/groups/{group_id}", dependencies=[Depends(require_project_migration_ok)]
)
async def dissolve_group(name: str, group_id: str):
    await invoke(name, lambda path, _project: store.dissolve_group(path, group_id))
    return {"success": True}


@router.get("/projects/{name}/novel-workflow/notes/{note_id}/source")
async def note_source(name: str, note_id: str):
    def read(path, project):
        notebook = store.state(path)
        if notebook is None:
            raise ValueError("No Notes")
        store.require_current(path, project, notebook["source_basis"])
        note = next((n for n in notebook["notes"] if n["id"] == note_id), None)
        if note is None:
            raise ValueError("Note not found")
        return {"text": "".join(p["text"] for p in chapters.chunks(path, project, note)), "sections": note["sections"]}

    return await invoke(name, read)


@router.post(
    "/projects/{name}/novel-workflow/groups/{group_id}/episode", dependencies=[Depends(require_project_migration_ok)]
)
async def arrange_episode(name: str, group_id: str):
    from lib.novel_workflow.production import arrange_episode as arrange

    def commit():
        return {"episode": arrange(get_project_manager(), name, group_id)}

    try:
        return await run_sync_transaction(commit)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class UnderstandingSettings(BaseModel):
    summary_max_chars: int = Field(ge=400, le=3000)
    understanding_enabled: bool


@router.patch("/projects/{name}/novel-workflow/settings", dependencies=[Depends(require_project_migration_ok)])
async def update_settings(name: str, req: UnderstandingSettings):
    from lib.novel_workflow.settings import update

    return await invoke(name, lambda path, _project: update(path, req.model_dump()))


class ScopeRequest(SourceRequest):
    note_ids: list[str] = Field(min_length=1, max_length=10000)


@router.put("/projects/{name}/novel-workflow/scope", dependencies=[Depends(require_project_migration_ok)])
async def set_scope(name: str, req: ScopeRequest):
    from lib.novel_workflow import scope

    return await invoke(name, lambda path, project: scope.configure(path, project, req.note_ids, req.source_basis))
