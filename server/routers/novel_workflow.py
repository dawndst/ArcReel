"""Chapter-first workflow endpoints; manual arrangement is separate from AI jobs."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from lib.infra.async_thread import run_sync_transaction
from lib.novel_workflow import chapters, store
from lib.novel_workflow.shot_production import ShotDecisions
from lib.project.project_manager import get_project_manager
from server.agent_toolset.envelope import json_value
from server.auth import CurrentUser
from server.dependencies import require_project_migration_ok
from server.tool_runtime import CallerContext, ProjectScope, Services, stop_note_workflow, submit_note_workflow

router = APIRouter()


def _context(project_name, user_id):
    pm = get_project_manager()
    return (
        ProjectScope(project_name=project_name, data_root=pm.data_root),
        CallerContext(user_id=user_id, source="webui"),
        Services.defaults(pm),
    )


@router.post("/projects/{name}/novel-workflow/stop")
async def stop_workflow(name: str, user: CurrentUser):
    from dataclasses import asdict

    scope, caller, services = _context(name, user.id)
    return asdict(await stop_note_workflow(scope, caller, services))


class SourceRequest(BaseModel):
    source_basis: str


class ReadingRequest(SourceRequest):
    action: Literal["read", "svt", "review", "understand", "scenes", "group_summary"]
    note_ids: list[str] = Field(min_length=1, max_length=10000)

    group_id: str | None = Field(default=None, max_length=100)


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
        if project.get("content_mode") != "drama":
            raise ValueError("章节 Note 工作流适用于剧情演绎项目")
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


class GroupUsageRequest(SourceRequest):
    usage: Literal["reference", "candidate"]


@router.patch("/projects/{name}/novel-workflow/groups/{group_id}", dependencies=[Depends(require_project_migration_ok)])
async def group_usage(name: str, group_id: str, req: GroupUsageRequest):
    from lib.novel_workflow.grouping import set_usage

    return await invoke(name, lambda path, project: set_usage(path, project, group_id, req.usage, req.source_basis))


class AssemblyRequest(SourceRequest):
    shot_ids: list[str] = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=200)
    request_id: str = Field(min_length=1, max_length=100)


@router.post("/projects/{name}/novel-workflow/episodes", dependencies=[Depends(require_project_migration_ok)])
async def assemble_episode(name: str, req: AssemblyRequest):
    from lib.novel_workflow.director import assemble

    return await invoke(
        name,
        lambda _path, _project: {
            "episode": assemble(get_project_manager(), name, req.shot_ids, req.title, req.source_basis, req.request_id)
        },
    )


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


class AdoptSVTRequest(SourceRequest):
    candidate_id: str = Field(min_length=1, max_length=100)


@router.post(
    "/projects/{name}/novel-workflow/notes/{note_id}/svt", dependencies=[Depends(require_project_migration_ok)]
)
async def adopt_svt(name: str, note_id: str, req: AdoptSVTRequest):
    from lib.novel_workflow.svt_contract import adopt

    return await invoke(name, lambda path, project: adopt(path, project, note_id, req.candidate_id, req.source_basis))


@router.get("/projects/{name}/novel-workflow/rules")
async def get_rules(name: str):
    from lib.novel_workflow.rule_catalog import catalog

    return await invoke(name, catalog)


class AttributionRequest(SourceRequest):
    segment_index: int = Field(ge=0)
    utterance_index: int = Field(ge=0)
    speaker: str = Field(min_length=1, max_length=200)
    shot_basis: str


@router.patch(
    "/projects/{name}/novel-workflow/shots/{shot_id}/speaker", dependencies=[Depends(require_project_migration_ok)]
)
async def attribute_speaker(name: str, shot_id: str, req: AttributionRequest):
    from lib.novel_workflow.scene_library import attribute_dialogue

    return await invoke(
        name,
        lambda path, project: attribute_dialogue(
            path,
            project,
            shot_id,
            req.segment_index,
            req.utterance_index,
            req.speaker,
            req.source_basis,
            req.shot_basis,
        ),
    )


class AdoptSceneRevision(SourceRequest):
    batch_basis: str
    revision_id: str


@router.post(
    "/projects/{name}/novel-workflow/scene-revisions/adopt", dependencies=[Depends(require_project_migration_ok)]
)
async def adopt_scene_revision(name: str, req: AdoptSceneRevision):
    from lib.novel_workflow.scene_review import adopt

    return await invoke(
        name, lambda path, project: adopt(path, project, req.batch_basis, req.revision_id, req.source_basis)
    )


class ConfirmSceneQuestions(SourceRequest):
    question_index: int = Field(ge=0)
    resolution: Literal["repaired", "false_positive"]
    batch_basis: str
    review_basis: str
    reason: str = Field(min_length=10, max_length=3000)


@router.post(
    "/projects/{name}/novel-workflow/scene-revisions/confirm", dependencies=[Depends(require_project_migration_ok)]
)
async def confirm_scene_questions(name: str, req: ConfirmSceneQuestions):
    from lib.novel_workflow.scene_review import confirm_questions

    return await invoke(
        name,
        lambda path, project: confirm_questions(
            path,
            project,
            req.batch_basis,
            req.source_basis,
            req.review_basis,
            req.reason,
            req.question_index,
            req.resolution,
        ),
    )


class ShotProductionRequest(SourceRequest):
    shot_basis: str
    decisions: ShotDecisions


@router.patch(
    "/projects/{name}/novel-workflow/shots/{shot_id}/production", dependencies=[Depends(require_project_migration_ok)]
)
async def update_shot_production(name: str, shot_id: str, req: ShotProductionRequest):
    from lib.novel_workflow.shot_production import update

    return await invoke(
        name, lambda path, project: update(path, project, shot_id, req.source_basis, req.shot_basis, req.decisions)
    )
