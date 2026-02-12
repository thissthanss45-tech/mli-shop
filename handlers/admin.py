from aiogram import Router, F
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models import User, UserRole

admin_router = Router()

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
            await message.answer("❌ Этот пользователь не найден в базе.\nПусть он сначала нажмет /start в боте.")
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
        except:
            pass
            
    except ValueError:
        await message.answer("❌ ID должен состоять только из цифр.")