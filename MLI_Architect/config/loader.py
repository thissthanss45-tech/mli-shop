import json
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict
from config.settings import PROFILES_DIR

# --- 1. Описание Структуры (Валидация) ---
# Эти классы описывают, как ДОЛЖЕН выглядеть JSON

class Thresholds(BaseModel):
    green_limit: float
    yellow_limit: float
    orange_limit: float
    pa_trigger: float

class Weights(BaseModel):
    L: Dict[str, float]  # Например: {"L-1": 1.0, "L-20": 1.5}
    I: Dict[str, float]

class ConflictProfile(BaseModel):
    conflict_id: str
    name: str
    sides: Dict[str, str]
    sources: List[str]
    weights: Weights
    thresholds: Thresholds
    keywords_ru: List[str]

# --- 2. Логика Загрузки ---

def load_profile(profile_name: str) -> ConflictProfile:
    """
    Загружает JSON файл из папки profiles/ и превращает его в объект.
    :param profile_name: имя файла без расширения (например, 'az_am')
    """
    file_path = PROFILES_DIR / f"{profile_name}.json"
    
    if not file_path.exists():
        raise FileNotFoundError(f"Критическая ошибка: Профиль {file_path} не найден!")

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Магия Pydantic: превращаем словарь в строгий объект
        profile = ConflictProfile(**data)
        return profile
    
    except json.JSONDecodeError:
        raise ValueError(f"Ошибка синтаксиса в файле {profile_name}.json (проверь запятые и кавычки)")
    except Exception as e:
        raise ValueError(f"Ошибка валидации профиля: {e}")


# --- Добавить в конец config/loader.py ---

def get_available_profiles() -> dict:
    """
    Сканирует папку profiles/ и возвращает словарь:
    {'az_am': 'Карабахский трек', 'cn_tw': 'Тайваньский пролив'}
    """
    profiles = {}
    # Перебираем все .json файлы в папке
    for file in PROFILES_DIR.glob("*.json"):
        try:
            # Читаем только заголовок, чтобы узнать имя, не загружая всё
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
                profiles[data['conflict_id']] = data.get('name', 'Без названия')
        except Exception as e:
            print(f"Ошибка чтения профиля {file}: {e}")
            
    return profiles