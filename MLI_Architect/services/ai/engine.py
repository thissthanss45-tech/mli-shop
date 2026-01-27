import json
import logging
import random
import re # Добавили регулярные выражения для чистки
from groq import AsyncGroq
from config.settings import settings
from services.ai.prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)

def extract_json_from_text(text: str):
    """
    Вырезает JSON-объект из строки, если AI добавил лишний текст.
    """
    try:
        # Ищем текст между первой { и последней }
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            return match.group(0)
        return text
    except Exception:
        return text

async def analyze_news(text_chunk: str, profile):
    """
    Анализирует текст через Llama-3.3, используя случайный ключ.
    """
    if not text_chunk:
        logger.error("❌ Ошибка: На вход подан пустой текст.")
        return None

    # --- КАРУСЕЛЬ КЛЮЧЕЙ ---
    try:
        if not settings.GROQ_KEYS:
             logger.error("❌ Ошибка: Список GROQ_KEYS пуст!")
             return None
             
        selected_key = random.choice(settings.GROQ_KEYS)
        # Проверка, что ключ не None
        if not selected_key:
             logger.error("❌ Ошибка: Выбран пустой API ключ!")
             return None
             
        client = AsyncGroq(api_key=selected_key)
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации клиента Groq: {e}")
        return None
    # -----------------------

    try:
        # Формируем промпт
        user_content = f"Конфликт: {profile.name}. Стороны: {profile.sides}. Текст: {text_chunk[:20000]}"
        
        logger.info(f"📤 Отправка запроса в Groq... (Ключ: ...{selected_key[-4:]})")
        
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.1,
            response_format={"type": "json_object"} 
        )
        
        response_content = chat_completion.choices[0].message.content
        
        # --- ХИРУРГИЯ JSON ---
        clean_json = extract_json_from_text(response_content)
        
        return json.loads(clean_json)

    except json.JSONDecodeError:
        logger.error(f"❌ Ошибка парсинга JSON. Ответ AI был: {response_content[:500]}...")
        return None
    except Exception as e:
        logger.error(f"❌ Критическая ошибка AI анализа: {e}")
        return None

async def ask_advisor(question: str, profile, current_intel: str = ""):
    """
    Отвечает на вопросы пользователя (Чат).
    """
    try:
        selected_key = random.choice(settings.GROQ_KEYS)
        client = AsyncGroq(api_key=selected_key)
    except Exception:
        return "⚠️ Ошибка конфигурации: нет доступных ключей API."
    
    if not current_intel:
        return "У меня пока нет свежих разведданных. Нажмите кнопку «🔄 Обновить»."

    prompt = (
        f"Ты — военный советник. Твоя задача — отвечать на вопросы командира, опираясь ТОЛЬКО на предоставленную сводку.\n"
        f"Вот последние разведданные:\n"
        f"\"\"\"{current_intel}\"\"\"\n\n"
        f"Вопрос командира: {question}\n\n"
        f"Отвечай кратко, по существу, называй конкретные населенные пункты и факты."
    )

    try:
        chat_completion = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": "You are a helpful military intelligence advisor. Speak Russian."},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.3,
        )
        return chat_completion.choices[0].message.content
    except Exception as e:
        return f"⚠️ Ошибка связи с советником: {e}"