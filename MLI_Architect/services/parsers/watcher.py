import asyncio
import requests
import trafilatura
from loguru import logger
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor()

# Маскируемся под обычный браузер
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7'
}

def fetch_url_masked(url: str):
    try:
        # Таймаут 10 секунд, чтобы не виснуть
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        
        # trafilatura пытается достать основной текст статьи
        text = trafilatura.extract(response.text, include_comments=False, include_tables=False)
        
        # Если trafilatura не справилась, берем просто "грязный" текст (html to string)
        if not text:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text(separator=' ', strip=True)
            
        return text if text else ""
    except Exception as e:
        logger.error(f"Ошибка скачивания {url}: {e}")
        return ""

async def fetch_news_async(url: str):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, fetch_url_masked, url)

async def get_daily_intel(sources: list, keywords: list = None):
    logger.info("📡 Начинаю гибридный парсинг...")
    tasks = [fetch_news_async(url) for url in sources]
    results = await asyncio.gather(*tasks)
    
    combined_text = ""
    
    for i, text in enumerate(results):
        source_url = sources[i]
        
        # Если текст совсем пустой — пропускаем
        if not text or len(text) < 50:
            logger.warning(f"⚠️ Пустой ответ от: {source_url}")
            continue
            
        # --- ЛОГИКА 1: ISW (Забираем всё) ---
        if "understandingwar.org" in source_url:
            logger.info(f"🇺🇸 ISW: Забираю отчет целиком ({len(text)} симв.)")
            combined_text += f"\n\n🚨 --- ОТЧЕТ ISW (USA) ---\n{text[:15000]}\n"
            continue

        # --- ЛОГИКА 2: Обычные источники (Умный фильтр + Страховка) ---
        logger.info(f"🌍 Парсинг источника: {source_url}")
        
        source_content = ""
        found_keywords = False
        
        if keywords:
            filtered_sentences = []
            sentences = text.split('.') # Бьем на предложения
            
            for s in sentences:
                s_clean = s.strip()
                if len(s_clean) < 20: continue 
                
                # Ищем совпадения
                if any(k.lower() in s_clean.lower() for k in keywords):
                    filtered_sentences.append(s_clean)
                    found_keywords = True
            
            if filtered_sentences:
                # Если нашли предложения с ключами — берем их
                source_content = ". ".join(filtered_sentences)
                logger.info(f"✅ Найдено {len(filtered_sentences)} предложений с ключами.")
            else:
                # --- ПЛАН Б (FALLBACK) ---
                # Если фильтр ничего не дал — берем начало текста как есть!
                logger.warning(f"⚠️ Ключевые слова не найдены в {source_url}. Беру 'сырой' текст.")
                source_content = text[:3000] # Берем первые 3000 знаков
        else:
            # Если ключей нет вообще — берем всё
            source_content = text[:3000]

        combined_text += f"\n\n📰 --- СВОДКА ({source_url}) ---\n{source_content}"

    return combined_text[:25000] # Общий лимит