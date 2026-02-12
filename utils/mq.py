from __future__ import annotations

import json

import aio_pika
from aio_pika.abc import AbstractRobustConnection as Connection

from config import settings


async def get_rabbitmq_connection() -> Connection:
    return await aio_pika.connect_robust(settings.rabbitmq_url)


async def send_task_to_queue(queue_name: str, data: dict) -> None:
    connection = await get_rabbitmq_connection()
    try:
        channel = await connection.channel()
        await channel.declare_queue(queue_name, durable=True)
        message = aio_pika.Message(
            body=json.dumps(data).encode("utf-8"),
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await channel.default_exchange.publish(message, routing_key=queue_name)
    finally:
        await connection.close()
