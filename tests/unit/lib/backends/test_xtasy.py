"""XTASY native media protocol: real HTTP serialization and resumable paid jobs."""

import json
from pathlib import Path

import httpx
import pytest
import respx

from arcreel_market_core.video_backend_contract import ResumeExpiredError, VideoGenerationRequest
from lib.backends.http_status_errors import AmbiguousSubmitError, ProviderRejectedError
from lib.backends.image_backends.base import ImageGenerationRequest, ReferenceImage
from lib.backends.image_backends.xtasy import XtasyImageBackend
from lib.backends.video_backends.xtasy import XtasyVideoBackend
from lib.infra.retry import NonRetryableError
from tests.fakes import bounded_poll_clock, captured_provider_job_ids

BASE = "https://xtasy.example.com/openapi/v1"


def finish(router, media):
    router.get(BASE + "/tasks/task-1").respond(
        json={
            "task": {
                "status": "succeeded",
                "outputs": [
                    {"id": "thumbnail", "mime_type": "image/png"},
                    {"id": "output", "mime_type": media + "/mp4" if media == "video" else "image/png"},
                ]
                if media == "video"
                else [{"id": "output", "mime_type": "image/png"}],
            }
        }
    )
    router.get(BASE + "/tasks/task-1/outputs/output/content").respond(content=b"generated-content")


@pytest.mark.asyncio
async def test_image_upload_ready_validation_and_authenticated_download(tmp_path: Path):
    reference = tmp_path / "ref.png"
    reference.write_bytes(b"reference-bytes")
    output = tmp_path / "result.png"
    with respx.mock as router, bounded_poll_clock(step=1):
        upload = router.post(BASE + "/files").respond(json={"file": {"id": "file-1"}})
        router.get(BASE + "/files/file-1").mock(
            side_effect=[
                httpx.Response(200, json={"status": "processing"}),
                httpx.Response(200, json={"status": "ready"}),
            ]
        )
        validate = router.post(BASE + "/images/generations/validate").respond(json={"valid": True})
        submit = router.post(BASE + "/images/generations").respond(json={"task": {"id": "task-1"}})
        finish(router, "image")
        result = await XtasyImageBackend(api_key="secret", base_url=BASE, model="image-model").generate(
            ImageGenerationRequest(
                prompt="draw",
                output_path=output,
                reference_images=[ReferenceImage(str(reference))],
                aspect_ratio="16:9",
                image_size="1K",
            )
        )
    payload = json.loads(submit.calls[0].request.content)
    assert (
        payload
        == json.loads(validate.calls[0].request.content)
        == {
            "model_id": "image-model",
            "prompt": "draw",
            "parameters": {"mode": "img2img", "aspect_ratio": "16:9", "resolution": "1K", "count": 1},
            "references": [{"role": "reference_image", "file_id": "file-1"}],
        }
    )
    assert b"reference-bytes" in upload.calls[0].request.content
    assert upload.calls[0].request.headers["Idempotency-Key"]
    assert result.image_path == output
    assert output.read_bytes() == b"generated-content"
    assert submit.calls[0].request.headers["Idempotency-Key"]


@pytest.mark.asyncio
@pytest.mark.parametrize("wan", [False, True])
async def test_video_parameters_and_durable_job(tmp_path: Path, wan: bool):
    output = tmp_path / "video.mp4"
    with respx.mock as router, captured_provider_job_ids() as jobs:
        router.post(BASE + "/videos/generations/validate").respond(json={"valid": True})
        submit = router.post(BASE + "/videos/generations").respond(json={"task_id": "task-1"})
        finish(router, "video")
        result = await XtasyVideoBackend(api_key="secret", base_url=BASE, model="video-model", wan=wan).generate(
            VideoGenerationRequest(
                prompt="move",
                output_path=output,
                duration_seconds=5,
                resolution="480p",
                aspect_ratio="16:9",
                generate_audio=not wan,
                task_id="local-1",
                execution_endpoint="xtasy-video",
            )
        )
    parameters = json.loads(submit.calls[0].request.content)["parameters"]
    assert parameters["duration_seconds" if wan else "duration"] == 5
    assert parameters["aspect_ratio"] == "16:9"
    assert parameters["resolution"] == "480p"
    assert ("generate_audio" in parameters) is not wan
    assert result.generate_audio is not wan
    assert output.read_bytes() == b"generated-content"
    assert result.task_id == "task-1"
    assert jobs[0]["job_id"] == "task-1"
    assert jobs[0]["base_url"] == BASE
    assert submit.calls[0].request.headers["Idempotency-Key"] == "local-1"


@pytest.mark.asyncio
async def test_validation_rejection_never_submits_paid_task(tmp_path: Path):
    with respx.mock as router:
        router.post(BASE + "/videos/generations/validate").respond(422, json={"error": {"message": "invalid duration"}})
        with pytest.raises(ProviderRejectedError) as error:
            await XtasyVideoBackend(api_key="secret", base_url=BASE, model="m").generate(
                VideoGenerationRequest(prompt="p", output_path=tmp_path / "out")
            )
    assert error.value.response.status_code == 422
    assert not (tmp_path / "out").exists()


@pytest.mark.asyncio
async def test_ambiguous_submit_is_not_repeated(tmp_path: Path):
    with respx.mock as router:
        router.post(BASE + "/videos/generations/validate").respond(json={"valid": True})
        submit = router.post(BASE + "/videos/generations").mock(side_effect=httpx.ReadTimeout("interrupted"))
        with pytest.raises(AmbiguousSubmitError):
            await XtasyVideoBackend(api_key="secret", base_url=BASE, model="m").generate(
                VideoGenerationRequest(prompt="p", output_path=tmp_path / "out")
            )
    assert submit.call_count == 1
    assert not (tmp_path / "out").exists()


@pytest.mark.asyncio
async def test_resume_uses_frozen_url_and_strips_auth_on_redirect(tmp_path: Path):
    output = tmp_path / "out.mp4"
    with respx.mock as router:
        router.get(BASE + "/tasks/old").respond(json={"status": "succeeded", "outputs": [{"id": "v", "type": "video"}]})
        download = router.get(BASE + "/tasks/old/outputs/v/content").respond(
            302, headers={"Location": "https://cdn.example.com/video.mp4"}
        )
        cdn = router.get("https://cdn.example.com/video.mp4").respond(content=b"video")
        result = await XtasyVideoBackend(
            api_key="secret", base_url="https://changed.example.com", model="m"
        ).resume_video(
            "old",
            VideoGenerationRequest(
                prompt="", output_path=output, submitted_base_url=BASE, start_image=tmp_path / "deleted.png"
            ),
        )
    assert result.task_id == "old"
    assert output.read_bytes() == b"video"
    assert download.calls[0].request.headers["Authorization"] == "Bearer secret"
    assert "Authorization" not in cdn.calls[0].request.headers


@pytest.mark.asyncio
async def test_expired_resume_and_incompatible_references(tmp_path: Path):
    backend = XtasyVideoBackend(api_key="secret", base_url=BASE, model="m")
    with respx.mock as router:
        router.get(BASE + "/tasks/old").respond(404, json={"error": "missing"})
        with pytest.raises(ResumeExpiredError):
            await backend.resume_video("old", VideoGenerationRequest(prompt="", output_path=tmp_path / "out"))
    with pytest.raises(NonRetryableError, match="cannot be combined"):
        await backend.generate(
            VideoGenerationRequest(
                prompt="", output_path=tmp_path / "out", start_image=tmp_path / "a", reference_images=[tmp_path / "b"]
            )
        )
    assert not (tmp_path / "out").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["frames", "references", "wan"])
async def test_video_reference_roles_and_mode(tmp_path: Path, mode: str):
    ref = tmp_path / "input.png"
    ref.write_bytes(b"image")
    output = tmp_path / "out.mp4"
    kwargs = (
        {"start_image": ref, "end_image": ref}
        if mode == "frames"
        else {"start_image": ref}
        if mode == "wan"
        else {"reference_images": [ref], "reference_audio_files": [ref]}
    )
    with respx.mock as router:
        router.post(BASE + "/files").respond(json={"file_id": "ref-1"})
        router.get(BASE + "/files/ref-1").respond(json={"file_status": "ready"})
        router.post(BASE + "/videos/generations/validate").respond(json={"valid": True})
        submit = router.post(BASE + "/videos/generations").respond(json={"id": "task-1"})
        finish(router, "video")
        result = await XtasyVideoBackend(api_key="secret", base_url=BASE, model="m", wan=mode == "wan").generate(
            VideoGenerationRequest(prompt="p", output_path=output, aspect_ratio="16:9", **kwargs)
        )
    body = json.loads(submit.calls[0].request.content)
    assert [r["role"] for r in body["references"]] == {
        "frames": ["first_frame", "last_frame"],
        "references": ["reference_image", "reference_audio"],
        "wan": ["first_frame"],
    }[mode]
    assert (
        body["parameters"]["mode"] == {"frames": "interpolation", "references": "multimodal", "wan": "img2video"}[mode]
    )
    assert body["parameters"]["aspect_ratio"] == ("adaptive" if mode == "frames" else "16:9")
    assert result.video_path.read_bytes() == b"generated-content"
