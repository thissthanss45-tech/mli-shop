import asyncio
from sqlalchemy import update
from database import async_session_maker
from models import User

async def reset_quotas():
    print("🔄 Обновляю лимиты для всех пользователей до 25...")
    async with async_session_maker() as session:
        stmt = update(User).values(ai_quota=25)
        await session.execute(stmt)
        await session.commit()
    print("✅ Готово! Теперь у всех 25 сообщений.")

if __name__ == "__main__":
    asyncio.run(reset_quotas())