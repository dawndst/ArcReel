"""Visible per-task generation cap; successful paid responses keep their normal caches."""

import asyncio

from lib.infra.async_thread import run_noninterruptible_sync
from lib.novel_understanding.service import NovelReadingInterrupted
from lib.novel_understanding.store import now
from lib.novel_workflow import settings, store


class WorkflowGenerator:
    def __init__(self, generator, path, state):
        self.generator = generator
        self.path = path
        self.state = state
        self.lock = asyncio.Lock()

    def __getattr__(self, name):
        return getattr(self.generator, name)

    @classmethod
    async def create(cls, generator, path, task_id, action):
        config = await asyncio.to_thread(settings.get, path)
        state = {
            "task_id": task_id,
            "action": action,
            "limit": config.get("max_model_calls", 100),
            "used": 0,
            "limit_reached": False,
            "started_at": now(),
        }
        await run_noninterruptible_sync(store.write, store.root(path) / "call_budget.json", state)
        return cls(generator, path, state)

    async def generate(self, request, **kwargs):
        async with self.lock:
            if self.state["used"] >= self.state["limit"]:
                self.state["limit_reached"] = True
                await run_noninterruptible_sync(store.write, store.root(self.path) / "call_budget.json", self.state)
                raise NovelReadingInterrupted(
                    "本次任务已达到模型生成次数上限；已完成结果已保存。可在阅读设置调整上限，或再次执行以复用缓存继续。"
                )
            self.state["used"] += 1
            await run_noninterruptible_sync(store.write, store.root(self.path) / "call_budget.json", self.state)
        return await self.generator.generate(request, **kwargs)
