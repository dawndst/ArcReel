"""XTASY 的文件、预检、异步任务与鉴权产物下载协议。"""

from __future__ import annotations

import asyncio
import mimetypes
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from urllib.parse import quote
from uuid import uuid4

import httpx

from arcreel_market_core.video_backend_contract import ProviderResponseStage, ResumeExpiredError
from lib.backends.artifact_download_guard import IMAGE_ARTIFACT_MAX_BYTES, VIDEO_ARTIFACT_MAX_BYTES
from lib.backends.backend_runtime import (
    notify_provider_response_to,
    poll_with_retry,
    provider_reason_summary,
    should_retry_poll,
    stream_to_file,
    submit_post,
    url_origin,
    with_artifact_retry,
)
from lib.backends.http_status_errors import AmbiguousSubmitError, provider_rejected_error, redacted_status_error
from lib.infra.retry import AsyncClock, NonRetryableError

ResponseSink = Callable[[ProviderResponseStage, object], Awaitable[None]]


def unwrap(body: dict[str, Any], key: str) -> dict[str, Any]:
    value = body.get(key, body)
    if not isinstance(value, dict):
        raise NonRetryableError(f"XTASY response has invalid {key}")
    return value


class XtasyClient:
    """不在客户端保存默认认证头，避免跨域取件时泄露凭据。"""

    def __init__(self, *, api_key: str, base_url: str, clock: AsyncClock | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_key}"}
        self.clock = clock

    async def json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        body: object | None = None,
        sink: ResponseSink | None = None,
        stage: ProviderResponseStage = "poll",
    ) -> dict[str, Any]:
        response = await client.request(method, self.base_url + path, json=body, headers=self.headers)
        await notify_provider_response_to(sink, stage, response.json() if response.is_success else response.text)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            if 400 <= response.status_code < 500:
                raise provider_rejected_error(exc, provider_reason=provider_reason_summary(response)) from None
            raise redacted_status_error(exc) from None
        result = response.json()
        if not isinstance(result, dict):
            raise NonRetryableError("XTASY response must be an object")
        return result

    async def upload(self, client: httpx.AsyncClient, path: Path, role: str) -> dict[str, str]:
        data = await asyncio.to_thread(path.read_bytes)
        mime = await asyncio.to_thread(mimetypes.guess_type, path.name)
        response = await client.post(
            self.base_url + "/files",
            headers={**self.headers, "Idempotency-Key": str(uuid4())},
            files={"file": (path.name, data, mime[0] or "application/octet-stream")},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise provider_rejected_error(exc, provider_reason=provider_reason_summary(response)) from None
        file = unwrap(response.json(), "file")
        file_id = file.get("id") or file.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            raise NonRetryableError("XTASY upload returned no file ID")

        async def fetch() -> dict[str, Any]:
            return unwrap(await self.json(client, "GET", "/files/" + quote(file_id, safe="")), "file")

        await poll_with_retry(
            poll_fn=fetch,
            is_done=lambda f: f.get("status", f.get("file_status")) == "ready",
            is_failed=lambda f: (
                "XTASY reference file processing failed"
                if f.get("status", f.get("file_status")) in {"failed", "expired", "deleted"}
                else None
            ),
            max_wait=180,
            retry_if=should_retry_poll,
            clock=self.clock,
            label="XTASY file",
        )
        return {"role": role, "file_id": file_id}

    async def submit(
        self,
        client: httpx.AsyncClient,
        media: str,
        body: dict[str, Any],
        *,
        sink: ResponseSink | None = None,
        request_key: str | None = None,
        on_unsafe: Callable[[], None] | None = None,
    ) -> str:
        path = f"/{media}s/generations"
        checked = await self.json(client, "POST", path + "/validate", body=body, sink=sink, stage="submit")
        if checked.get("valid", checked.get("is_valid", True)) is False or checked.get("error"):
            raise NonRetryableError("XTASY request validation failed")
        headers = {**self.headers, "Idempotency-Key": request_key or str(uuid4())}
        if on_unsafe is not None:
            on_unsafe()
        response = await submit_post(
            lambda: client.post(self.base_url + path, json=body, headers=headers),
            provider="XTASY",
        )
        try:
            payload = response.json()
            await notify_provider_response_to(sink, "submit", payload)
            task = unwrap(payload, "task")
            job_id = task.get("id") or task.get("task_id")
            if not isinstance(job_id, str) or not job_id:
                raise ValueError("missing task ID")
        except (ValueError, TypeError, NonRetryableError) as exc:
            raise AmbiguousSubmitError(provider="XTASY") from exc
        return job_id

    async def collect(
        self,
        client: httpx.AsyncClient,
        job_id: str,
        media: str,
        output: Path,
        *,
        max_wait: float,
        sink: ResponseSink | None = None,
        resume: bool = False,
    ) -> str:
        path = "/tasks/" + quote(job_id, safe="")

        async def fetch() -> dict[str, Any]:
            try:
                return unwrap(await self.json(client, "GET", path, sink=sink), "task")
            except httpx.HTTPStatusError as exc:
                if resume and exc.response.status_code == 404:
                    raise ResumeExpiredError(job_id=job_id, provider="XTASY") from exc
                raise

        task = await poll_with_retry(
            poll_fn=fetch,
            is_done=lambda t: t.get("status") in {"succeeded", "success", "completed"},
            is_failed=lambda t: (
                str(t.get("error") or "XTASY task failed")
                if t.get("status") in {"failed", "cancelled", "canceled", "expired"}
                else None
            ),
            max_wait=max_wait,
            retry_if=should_retry_poll,
            clock=self.clock,
            label=f"XTASY {job_id}",
        )
        outputs = task.get("outputs") or task.get("result", {}).get("outputs", [])
        # A video task can also return a last-frame image; select by media metadata, not list order.
        candidates = [
            o
            for o in outputs
            if isinstance(o, dict)
            and (
                str(o.get("mime_type", o.get("content_type", ""))).startswith(media + "/")
                or o.get("type") == media
                or o.get("kind") == media
            )
        ]
        if not candidates and len(outputs) == 1:
            candidates = outputs
        if not candidates:
            raise NonRetryableError(f"XTASY task {job_id} returned no identifiable {media} output")
        output_id = candidates[0].get("id") or candidates[0].get("output_id")
        if not isinstance(output_id, str) or not output_id:
            raise NonRetryableError(f"XTASY task {job_id} returned no output ID")
        url = self.base_url + path + "/outputs/" + quote(output_id, safe="") + "/content"

        async def download() -> None:
            await stream_to_file(
                client,
                url,
                output,
                headers=self.headers,
                credential_origin=url_origin(self.base_url),
                max_bytes=IMAGE_ARTIFACT_MAX_BYTES if media == "image" else VIDEO_ARTIFACT_MAX_BYTES,
            )

        await with_artifact_retry(download, label=f"XTASY {job_id}", max_wait=max_wait)
        return url
