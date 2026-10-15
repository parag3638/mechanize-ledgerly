"""The charges stream: the API appends new charge ids, the worker consumes them.

Redis Streams with one consumer group. Entries stay pending until the worker
acknowledges them, so a crashed worker's charges are reclaimed on restart.
"""

from typing import Any, cast

import redis

from ledgerly.config import get_settings
from ledgerly.log import get_logger

log = get_logger(__name__)

Entry = tuple[str, dict[str, str]]


def connect() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def publish_charge_created(client: redis.Redis, charge_id: str) -> None:
    client.xadd(get_settings().stream_name, {"charge_id": charge_id})


def ensure_group(client: redis.Redis) -> None:
    settings = get_settings()
    try:
        client.xgroup_create(settings.stream_name, settings.consumer_group, id="0", mkstream=True)
    except redis.ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def read(client: redis.Redis, consumer: str, count: int, block_ms: int) -> list[Entry]:
    settings = get_settings()
    reply = client.xreadgroup(
        settings.consumer_group, consumer, {settings.stream_name: ">"}, count=count, block=block_ms
    )
    if not reply:
        return []
    entries: list[Entry] = []
    for _stream, messages in cast(list[Any], reply):
        entries.extend((msg_id, fields) for msg_id, fields in messages)
    return entries


def reclaim(client: redis.Redis, consumer: str, min_idle_ms: int) -> list[Entry]:
    """Take over entries another consumer read but never acknowledged."""
    settings = get_settings()
    reply = cast(
        list[Any],
        client.xautoclaim(
            settings.stream_name, settings.consumer_group, consumer, min_idle_ms, "0-0", count=1000
        ),
    )
    return [(msg_id, fields) for msg_id, fields in reply[1] if fields]


def ack(client: redis.Redis, msg_id: str) -> None:
    settings = get_settings()
    client.xack(settings.stream_name, settings.consumer_group, msg_id)


def backlog(client: redis.Redis) -> int:
    settings = get_settings()
    try:
        groups = cast(list[dict[str, Any]], client.xinfo_groups(settings.stream_name))
    except redis.ResponseError:
        return 0
    for group in groups:
        if group.get("name") == settings.consumer_group:
            return int(group.get("lag") or 0)
    return 0
