from __future__ import annotations

import json
from datetime import datetime
from uuid import uuid4

import aio_pika
from aio_pika.abc import AbstractRobustConnection as Connection

from config import settings


async def get_rabbitmq_connection() -> Connection:
    return await aio_pika.connect_robust(settings.rabbitmq_url)


async def send_task_to_queue(queue_name: str, data: dict) -> str:
    request_id = str(data.get("request_id") or uuid4())
    data["request_id"] = request_id
    data.setdefault("enqueued_at_ts", datetime.utcnow().timestamp())
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    if len(body) > settings.max_queue_payload_bytes:
        raise ValueError(
            f"Queue payload too large: {len(body)} bytes > {settings.max_queue_payload_bytes} bytes"
        )

    connection = await get_rabbitmq_connection()
    try:
        channel = await connection.channel()
        await channel.declare_queue(queue_name, durable=True)
        message = aio_pika.Message(
            body=body,
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=request_id,
        )
        await channel.default_exchange.publish(message, routing_key=queue_name)
    finally:
        await connection.close()
    return request_id
