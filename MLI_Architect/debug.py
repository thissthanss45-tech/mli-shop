import asyncio
from services.parsers.watcher import fetch_news
from config.loader import load_profile

async def test_vision():
    # Загружаем профиль (Украина-РФ)
    profile = load_profile("ru_ua")
    print(f"🔬 ДИАГНОСТИКА ЗРЕНИЯ БОТА [{profile.name}]\n")

    for url in profile.sources:
        print(f"🌍 Проверяю источник: {url}")
        try:
            # Скачиваем текст
            text = await fetch_news(url)
            
            # Показываем результат
            if len(text) < 100:
                print(f"❌ ОШИБКА: Контента слишком мало ({len(text)} симв). Скорее всего, защита или капча.")
            else:
                print(f"✅ УСПЕХ: Скачано {len(text)} символов.")
                print(f"🔎 ПЕРВЫЕ 200 СИМВОЛОВ:\n{text[:200]}...")
                print("-" * 50)
                
        except Exception as e:
            print(f"❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        print("\n")

if __name__ == "__main__":
    asyncio.run(test_vision())