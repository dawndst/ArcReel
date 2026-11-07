"""XTASY 文件引用与异步图像任务通道。"""

from pathlib import Path

from lib.backends.artifact_download_guard import artifact_http_client
from lib.backends.image_backends.base import (
    BOTH_IMAGE_CAPABILITIES,
    ImageCapability,
    ImageGenerationRequest,
    ImageGenerationResult,
)
from lib.backends.xtasy_shared import XtasyClient
from lib.infra.retry import AsyncClock


class XtasyImageBackend:
    CHANNEL_CAPABILITIES = BOTH_IMAGE_CAPABILITIES
    CHANNEL_REFERENCE_LIMIT = None

    def __init__(self, *, api_key: str, base_url: str, model: str, clock: AsyncClock | None = None) -> None:
        self._client = XtasyClient(api_key=api_key, base_url=base_url, clock=clock)
        self.model = model
        self.name = "xtasy"

    @property
    def capabilities(self) -> set[ImageCapability]:
        return set(self.CHANNEL_CAPABILITIES)

    async def reference_image_limit(self) -> int | None:
        return self.CHANNEL_REFERENCE_LIMIT

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        async with artifact_http_client(timeout=120) as client:
            refs = [
                await self._client.upload(client, Path(ref.path), "reference_image") for ref in request.reference_images
            ]
            parameters = {"mode": "img2img" if refs else "txt2img", "aspect_ratio": request.aspect_ratio, "count": 1}
            if request.image_size:
                parameters["resolution"] = request.image_size
            job_id = await self._client.submit(
                client,
                "image",
                {
                    "model_id": self.model,
                    "prompt": request.prompt,
                    "parameters": parameters,
                    "references": refs,
                },
                sink=request.on_provider_response,
            )
            uri = await self._client.collect(
                client, job_id, "image", request.output_path, max_wait=1800, sink=request.on_provider_response
            )
        return ImageGenerationResult(
            image_path=request.output_path, provider=self.name, model=self.model, image_uri=uri
        )
