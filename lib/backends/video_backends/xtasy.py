"""XTASY 多模态视频与 Wan 视频协议；已提交任务可直接续取。"""

from arcreel_market_core.video_backend_contract import (
    ReferenceAudioMode,
    VideoAudioMode,
    VideoCapabilities,
    VideoGenerationRequest,
    VideoGenerationResult,
)
from lib.backends.artifact_download_guard import artifact_http_client
from lib.backends.backend_runtime import ProviderJobIdPersistenceMixin
from lib.backends.xtasy_shared import XtasyClient
from lib.infra.retry import AsyncClock, NonRetryableError


def xtasy_video_capabilities(*, wan: bool = False) -> VideoCapabilities:
    return VideoCapabilities(
        last_frame=not wan,
        max_reference_images=0 if wan else None,
        reference_audio_mode=ReferenceAudioMode.NONE if wan else ReferenceAudioMode.DIRECT,
        max_reference_audio_count=0 if wan else None,
        first_frame_ratio_adaptive_only=not wan,
        audio_track=VideoAudioMode.ALWAYS_OFF if wan else VideoAudioMode.CONTROLLABLE,
    )


class XtasyVideoBackend(ProviderJobIdPersistenceMixin):
    def __init__(
        self, *, api_key: str, base_url: str, model: str, wan: bool = False, clock: AsyncClock | None = None
    ) -> None:
        self._api_key = api_key
        self._client = XtasyClient(api_key=api_key, base_url=base_url, clock=clock)
        self._wan = wan
        self.model = model
        self.name = "xtasy"

    @property
    def video_capabilities(self) -> VideoCapabilities:
        return xtasy_video_capabilities(wan=self._wan)

    async def generate(self, request: VideoGenerationRequest) -> VideoGenerationResult:
        if request.end_image and not request.start_image:
            raise NonRetryableError("XTASY last frame requires a first frame")
        if request.start_image and (request.reference_images or request.reference_audio_files):
            raise NonRetryableError("XTASY first/last frames cannot be combined with multimodal references")
        if self._wan and (request.end_image or request.reference_images or request.reference_audio_files):
            raise NonRetryableError("XTASY Wan endpoint accepts only a first frame")
        if request.reference_audio_files and not request.generate_audio:
            raise NonRetryableError("XTASY audio references require generated audio")
        parameters: dict[str, object] = {"aspect_ratio": request.aspect_ratio}
        if request.resolution:
            parameters["resolution"] = request.resolution
        parameters["duration_seconds" if self._wan else "duration"] = request.duration_seconds
        if self._wan:
            parameters["mode"] = "img2video" if request.start_image else "text2video"
        else:
            parameters.update(
                generate_audio=request.generate_audio, output_format="mp4", return_last_frame=False, watermark=False
            )
            parameters["mode"] = (
                "interpolation"
                if request.start_image
                else "multimodal"
                if (request.reference_images or request.reference_audio_files)
                else "text2video"
            )
            if request.start_image:
                parameters["aspect_ratio"] = "adaptive"
        async with artifact_http_client(timeout=120) as client:
            refs = []
            for role, paths in (
                ("first_frame", [request.start_image] if request.start_image else []),
                ("last_frame", [request.end_image] if request.end_image else []),
                ("reference_image", request.reference_images or []),
                ("reference_audio", request.reference_audio_files or []),
            ):
                refs.extend([await self._client.upload(client, path, role) for path in paths])
            job_id = await self._client.submit(
                client,
                "video",
                {
                    "model_id": self.model,
                    "prompt": request.prompt,
                    "parameters": parameters,
                    "references": refs,
                },
                sink=request.on_provider_response,
                request_key=request.task_id,
                on_unsafe=request.on_provider_resubmit_unsafe,
            )
            await self._persist_provider_job_id(request, job_id, provider=self.name, endpoint=self._client.base_url)
        return await self._collect(job_id, request, resume=False)

    async def resume_video(self, job_id: str, request: VideoGenerationRequest) -> VideoGenerationResult:
        return await self._collect(job_id, request, resume=True)

    async def _collect(self, job_id: str, request: VideoGenerationRequest, *, resume: bool) -> VideoGenerationResult:
        api = XtasyClient(
            api_key=self._api_key,
            base_url=request.submitted_base_url or self._client.base_url,
            clock=self._client.clock,
        )
        async with artifact_http_client(timeout=120) as client:
            uri = await api.collect(
                client,
                job_id,
                "video",
                request.output_path,
                max_wait=request.poll_timeout_seconds,
                sink=request.on_provider_response,
                resume=resume,
            )
        return VideoGenerationResult(
            video_path=request.output_path,
            provider=self.name,
            model=self.model,
            duration_seconds=request.duration_seconds,
            video_uri=uri,
            task_id=job_id,
            generate_audio=False if self._wan else request.generate_audio,
        )
