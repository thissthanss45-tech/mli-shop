from __future__ import annotations

import logging

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import Message


async def safe_delete_message(message: Message, logger: logging.Logger, context: str) -> bool:
    try:
        await message.delete()
        return True
    except TelegramBadRequest as exc:
        logger.debug("Skip message delete [%s]: %s", context, exc)
        return False
    except Exception as exc:
        logger.warning("Message delete failed [%s]: %s", context, exc)
        return False


async def safe_edit_text(
    message: Message,
    logger: logging.Logger,
    context: str,
    text: str,
    *,
    reply_markup=None,
    parse_mode: str | None = None,
) -> bool:
    try:
        await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        return True
    except TelegramBadRequest as exc:
        lowered = str(exc).lower()
        if "message is not modified" in lowered:
            logger.debug("Skip message edit [%s]: message not modified", context)
            return False
        logger.warning("Message edit rejected [%s]: %s", context, exc)
        return False
    except Exception as exc:
        logger.warning("Message edit failed [%s]: %s", context, exc)
        return False
