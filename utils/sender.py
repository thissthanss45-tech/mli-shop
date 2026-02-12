from __future__ import annotations

import html
from aiogram import Bot
from aiogram.types import Message, InlineKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest


async def send_safe_html(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
    max_length: int = 4096
) -> None:
    """
    Безопасная отправка HTML-сообщений с обработкой ошибок тегов.
    Разбивает длинные сообщения на части.
    """
    if not text:
        return

    # Очистка текста от потенциально опасных тегов
    safe_text = html.escape(text)
    
    # Восстанавливаем безопасные теги
    safe_text = safe_text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
    safe_text = safe_text.replace('&lt;i&gt;', '<i>').replace('&lt;/i&gt;', '</i>')
    safe_text = safe_text.replace('&lt;code&gt;', '<code>').replace('&lt;/code&gt;', '</code>')
    safe_text = safe_text.replace('&lt;pre&gt;', '<pre>').replace('&lt;/pre&gt;', '</pre>')
    
    # Если текст слишком длинный, разбиваем на части
    if len(safe_text) > max_length:
        parts = []
        current_part = ""
        
        for line in safe_text.split('\n'):
            if len(current_part) + len(line) + 1 > max_length:
                parts.append(current_part)
                current_part = line + '\n'
            else:
                current_part += line + '\n'
        
        if current_part:
            parts.append(current_part)
        
        # Отправляем все части
        for i, part in enumerate(parts):
            try:
                if i == len(parts) - 1:
                    await message.answer(part, parse_mode="HTML", reply_markup=reply_markup)
                else:
                    await message.answer(part, parse_mode="HTML")
            except TelegramBadRequest:
                # Если не удалось отправить как HTML, пробуем без форматирования
                try:
                    clean_part = html.unescape(part)
                    if i == len(parts) - 1:
                        await message.answer(clean_part, reply_markup=reply_markup)
                    else:
                        await message.answer(clean_part)
                except Exception as e:
                    await message.answer(f"[Ошибка форматирования: {str(e)}]")
    else:
        try:
            await message.answer(safe_text, parse_mode="HTML", reply_markup=reply_markup)
        except TelegramBadRequest:
            # Если не удалось отправить как HTML, пробуем без форматирования
            try:
                clean_text = html.unescape(safe_text)
                await message.answer(clean_text, reply_markup=reply_markup)
            except Exception as e:
                await message.answer(f"[Ошибка форматирования: {str(e)}]")


async def safe_edit_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None
) -> bool:
    """
    Безопасное редактирование сообщения с обработкой ошибок.
    Возвращает True, если редактирование прошло успешно.
    """
    try:
        safe_text = html.escape(text)
        safe_text = safe_text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
        safe_text = safe_text.replace('&lt;i&gt;', '<i>').replace('&lt;/i&gt;', '</i>')
        
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=safe_text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )
        return True
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return True  # Сообщение не изменилось, это не ошибка
        elif "message to edit not found" in str(e):
            return False  # Сообщение не найдено
        else:
            try:
                clean_text = html.unescape(safe_text)
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=clean_text,
                    reply_markup=reply_markup
                )
                return True
            except:
                return False
    except Exception:
        return False