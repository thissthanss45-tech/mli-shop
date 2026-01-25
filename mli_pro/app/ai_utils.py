import os
import aiohttp
import json
import pandas as pd
from pypdf import PdfReader
from docx import Document
from app.config import LLM_API_KEY, LLM_API_URL, TAVILY_API_KEY

# Хранилище контекста
user_contexts = {}
MAX_HISTORY = 10 

# --- 1. УПРАВЛЕНИЕ ПАМЯТЬЮ ---

def get_user_context(user_id):
    if user_id not in user_contexts:
        user_contexts[user_id] = [{
            "role": "system", 
            "content": "Ты - опытный Главный Инженер (MLI). Отвечай кратко, по делу, используй СНиП/ГОСТ РФ."
        }]
    return user_contexts[user_id]

def clear_context(user_id):
    if user_id in user_contexts:
        del user_contexts[user_id]
    return "🧹 Память очищена."

def add_to_context(user_id, role, content):
    context = get_user_context(user_id)
    context.append({"role": role, "content": content})
    
    # Оставляем System [0] + последние N сообщений
    if len(context) > MAX_HISTORY + 1:
        user_contexts[user_id] = [context[0]] + context[-(MAX_HISTORY):]

# --- 2. ПОИСК И ФАЙЛЫ ---

async def search_tavily(query):
    if not TAVILY_API_KEY: return None
    
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": TAVILY_API_KEY, 
        "query": query, 
        "search_depth": "basic", 
        "include_answer": True, 
        "max_results": 3
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    answer = data.get("answer", "")
                    results = "\n".join([f"- {r['title']}: {r['url']}" for r in data.get("results", [])])
                    return f"{answer}\nИсточники:\n{results}"
                return None
    except Exception as e:
        print(f"Ошибка Tavily: {e}")
        return None

def read_document_content(file_path):
    ext = file_path.split('.')[-1].lower()
    text = ""
    try:
        if ext == 'xlsx':
            df = pd.read_excel(file_path)
            text = f"📄 Excel:\n{df.to_string(index=False)[:4000]}"
        elif ext == 'pdf':
            reader = PdfReader(file_path)
            for page in reader.pages: text += page.extract_text() + "\n"
            text = f"📄 PDF:\n{text[:4000]}"
        elif ext == 'docx':
            doc = Document(file_path)
            for para in doc.paragraphs: text += para.text + "\n"
            text = f"📄 Word:\n{text[:4000]}"
        return text
    except Exception:
        return None

# --- 3. ЗАПРОС К LLM (Стабильная версия) ---

async def ask_ai(user_id, user_message, file_path=None, use_search=False):
    # Формируем полный текст запроса
    final_content = user_message

    # 1. Если есть файл
    if file_path:
        content = read_document_content(file_path)
        if content: 
            final_content += f"\n\n[Данные из файла]:\n{content}"
    
    # 2. Если есть поиск (Вшиваем в сообщение пользователя, чтобы не ломать историю)
    if use_search:
        search_res = await search_tavily(user_message)
        if search_res:
            final_content += f"\n\n[Информация из интернета]:\n{search_res}"

    # 3. Сохраняем в историю
    add_to_context(user_id, "user", final_content)
    
    # Получаем актуальный контекст
    context = get_user_context(user_id)
    
    if not LLM_API_KEY: return "⚠️ Ошибка: Нет ключа API."

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": context,
        "temperature": 0.6
    }

    try:
        # Увеличим таймаут, чтобы бот не "падал", если Llama думает долго
        timeout = aiohttp.ClientTimeout(total=60) 
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(LLM_API_URL, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    ans = data['choices'][0]['message']['content']
                    add_to_context(user_id, "assistant", ans)
                    return ans
                else:
                    err_text = await resp.text()
                    print(f"API Error {resp.status}: {err_text}") # Пишем в консоль
                    return f"⚠️ Ошибка провайдера ({resp.status}). Попробуйте позже."
    except Exception as e:
        print(f"Exception in ask_ai: {e}") # Пишем ошибку в консоль
        return "⚠️ Произошла ошибка соединения. Повторите запрос."