import matplotlib.pyplot as plt
import io
import matplotlib.dates as mdates
from datetime import datetime

def plot_trend(history: list, profile):
    """
    Рисует график риска R и возвращает объект картинки (BytesIO).
    history: список кортежей [(date_str, r_val), ...]
    """
    # Разбираем данные
    dates = [datetime.strptime(row[0], "%Y-%m-%d") for row in history]
    values = [row[1] for row in history]

    # Настройка стиля
    plt.style.use('dark_background') # Темная тема (хакерский стиль)
    fig, ax = plt.subplots(figsize=(10, 6))
    
    # Рисуем линию риска
    ax.plot(dates, values, color='#00ff00', marker='o', linewidth=2, label='Индекс R')
    
    # Заливка под графиком
    ax.fill_between(dates, values, color='#00ff00', alpha=0.1)

    # Рисуем линии порогов (Зоны)
    # Желтая линия
    ax.axhline(y=profile.thresholds.yellow_limit, color='yellow', linestyle='--', alpha=0.5, label='Желтая зона')
    # Оранжевая линия
    ax.axhline(y=profile.thresholds.orange_limit, color='orange', linestyle='--', alpha=0.5, label='Оранжевая зона')
    # Красная линия (АЛАРМ)
    if profile.thresholds.orange_limit < 20: # Рисуем, если влезает
        ax.axhline(y=profile.thresholds.orange_limit + 3, color='red', linestyle='--', alpha=0.5, label='Красная зона')

    # Настройки осей
    ax.set_title(f"Динамика Риска: {profile.name}", fontsize=14, color='white', pad=20)
    ax.set_ylabel("Индекс R (MLI 2.0)", fontsize=12)
    ax.grid(True, color='#333333', linestyle='--')
    
    # Формат дат снизу
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d.%m'))
    plt.xticks(rotation=45)
    
    # Легенда
    ax.legend(loc='upper left')

    # Сохраняем в буфер (память)
    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    plt.close()
    
    return buf