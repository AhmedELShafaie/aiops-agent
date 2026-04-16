from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from services.common.aiops_common.config import get_settings


def get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


async def publish_stream(redis: Redis, stream: str, payload: dict[str, Any]) -> str:
    message = {"payload": json.dumps(payload, default=str)}
    return await redis.xadd(stream, message)


async def consume_stream(
    redis: Redis,
    stream: str,
    last_id: str = "$",
    block_ms: int = 3000,
    count: int = 20,
) -> tuple[str, list[dict[str, Any]]]:
    result = await redis.xread({stream: last_id}, block=block_ms, count=count)
    if not result:
        return last_id, []

    _, entries = result[0]
    events: list[dict[str, Any]] = []
    new_last_id = last_id
    for entry_id, values in entries:
        payload = json.loads(values["payload"])
        events.append(payload)
        new_last_id = entry_id
    return new_last_id, events
