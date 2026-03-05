from datetime import datetime
from io import StringIO
import logging

from aiogram import Router, F
from aiogram.types import Message, BufferedInputFile
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramNotFound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from redis.asyncio import Redis

from config import settings
from models import User, UserRole, AIChatLog

admin_router = Router()
logger = logging.getLogger(__name__)

AI_PROVIDER_KEY = "ai:provider"
AI_MODEL_KEY = "ai:model"

redis_cache: Redis | None = None


def _get_redis_cache() -> Redis | None:
    global redis_cache
    if redis_cache is None:
        try:
            redis_cache = Redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        except Exception:
            redis_cache = None
    return redis_cache


async def _get_ai_provider_override() -> tuple[str | None, str | None]:
    cache = _get_redis_cache()
    if not cache:
        return None, None
    try:
        provider = await cache.get(AI_PROVIDER_KEY)
        model = await cache.get(AI_MODEL_KEY)
        return provider, model
    except Exception:
        return None, None


def _get_default_model(provider: str) -> str:
    if provider == "deepseek":
        return settings.deepseek_model or "deepseek-chat"
    return settings.groq_model or "llama-3.3-70b-versatile"

@admin_router.message(F.text.startswith("/set_seller"))
async def set_staff_role(message: Message, session: AsyncSession):
    """
    Команда: /set_seller 123456789
    Назначает пользователя Сотрудником (STAFF).
    """
    if message.from_user.id != settings.owner_id:
        return

    try:
        parts = message.text.split()
        if len(parts) != 2:
            await message.answer("⚠️ Ошибка формата.\nПиши так: `/set_seller 123456789`", parse_mode="Markdown")
            return
        
        target_id = int(parts[1])
        
        stmt = select(User).where(User.tg_id == target_id)
        result = await session.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            await message.answer("⚠️ Этот пользователь не найден в базе.\nПусть он сначала нажмет /start в боте.")
            return
            
        user.role = UserRole.STAFF.value
        await session.commit()
        
        await message.answer(
            f"✅ <b>Успешно!</b>\n"
            f"Пользователь {user.full_name} назначен <b>Сотрудником (STAFF)</b>.\n"
            f"Теперь ему доступна витрина.",
            parse_mode="HTML"
        )
        
        try:
            await message.bot.send_message(
                target_id, 
                "👨‍💼 <b>Поздравляем!</b>\n"
                "Вы назначены сотрудником магазина.\n"
                "Нажмите /start, чтобы открыть рабочий интерфейс.",
                parse_mode="HTML"
            )
        except (TelegramBadRequest, TelegramForbiddenError, TelegramNotFound) as exc:
            logger.warning("Failed to notify new staff member %s: %s", target_id, exc)
            
    except ValueError:
        await message.answer("⚠️ ID должен состоять только из цифр.")


@admin_router.message(F.text.startswith("/ai_provider"))
async def set_ai_provider(message: Message) -> None:
    if message.from_user.id != settings.owner_id:
        return

    parts = message.text.split()
    provider_override, model_override = await _get_ai_provider_override()
    current_provider = (provider_override or settings.ai_provider or "groq").lower()
    current_model = model_override or settings.ai_model or _get_default_model(current_provider)

    if len(parts) == 1:
        await message.answer(
            "⚙️ <b>Текущий AI провайдер</b>\n"
            f"Провайдер: <code>{current_provider}</code>\n"
            f"Модель: <code>{current_model}</code>\n\n"
            "Команды:\n"
            "• /ai_provider groq [model]\n"
            "• /ai_provider deepseek [model]\n"
            "• /ai_provider reset",
            parse_mode="HTML",
        )
        return

    target = parts[1].strip().lower()
    if target in {"reset", "default"}:
        cache = _get_redis_cache()
        if cache:
            try:
                await cache.delete(AI_PROVIDER_KEY)
                await cache.delete(AI_MODEL_KEY)
            except Exception:
                pass
        await message.answer("✅ Настройки провайдера сброшены до значений из .env")
        return

    if target not in {"groq", "deepseek"}:
        await message.answer("⚠️ Провайдер не поддерживается. Доступно: groq, deepseek.")
        return

    model = parts[2].strip() if len(parts) >= 3 else ""
    cache = _get_redis_cache()
    if not cache:
        await message.answer("⚠️ Redis недоступен. Переключение провайдера невозможно.")
        return

    try:
        await cache.set(AI_PROVIDER_KEY, target)
        if model:
            await cache.set(AI_MODEL_KEY, model)
        else:
            await cache.delete(AI_MODEL_KEY)
    except Exception:
        await message.answer("⚠️ Не удалось сохранить настройку провайдера.")
        return

    await message.answer(
        "✅ Провайдер обновлен.\n"
        f"Провайдер: <code>{target}</code>\n"
        f"Модель: <code>{model or _get_default_model(target)}</code>",
        parse_mode="HTML",
    )


@admin_router.message(F.text.startswith("/ai_audit"))
async def export_ai_audit(message: Message, session: AsyncSession) -> None:
    if message.from_user.id != settings.owner_id:
        return

    stmt = (
        select(AIChatLog, User)
        .outerjoin(User, User.tg_id == AIChatLog.user_tg_id)
        .order_by(AIChatLog.created_at.asc(), AIChatLog.id.asc())
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        await message.answer("📭 Логи ИИ пока пустые.")
        return

    output = StringIO()
    output.write("АУДИТ ДИАЛОГОВ ИИ\n")
    output.write(f"Сформировано: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
    output.write(f"Всего записей: {len(rows)}\n")
    output.write("=" * 80 + "\n\n")

    for log_row, user in rows:
        created_at = log_row.created_at.strftime("%Y-%m-%d %H:%M:%S") if log_row.created_at else ""
        if user and user.username:
            client_name = f"@{user.username}"
        elif user:
            client_name = user.full_name
        else:
            client_name = "Неизвестно"

        role_label = "ИИ" if log_row.role == "assistant" else "Клиент"
        output.write(f"[{created_at}]\n")
        output.write(f"Telegram ID: {log_row.user_tg_id}\n")
        output.write(f"Имя клиента: {client_name}\n")
        output.write(f"Роль: {role_label}\n")
        output.write("Текст:\n")
        output.write(f"{log_row.content}\n")
        output.write("-" * 80 + "\n")

    report_bytes = output.getvalue().encode("utf-8")
    filename = f"ai_audit_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.txt"
    await message.answer_document(
        BufferedInputFile(report_bytes, filename=filename),
        caption=f"📄 Аудит диалогов ИИ (TXT): {len(rows)} записей",
    )