from aiogram import Router, F, types
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from app.keyboards import get_main_menu
from app.ai_utils import ai_web_search

router = Router()

class SearchState(StatesGroup):
    waiting_for_query = State()

# 1. Нажали "🌐 Поиск"
@router.message(F.text == "🌐 Поиск")
async def search_start(message: types.Message, state: FSMContext):
    await message.answer(
        "🌐 **Режим Глобального Поиска**\n"
        "Я найду актуальные цены, нормы или информацию в интернете.\n\n"
        "Что искать? (например: 'Цена арматуры А500С в Москве сегодня')"
    )
    await state.set_state(SearchState.waiting_for_query)

# 2. Обработка запроса
@router.message(SearchState.waiting_for_query)
async def process_search(message: types.Message, state: FSMContext):
    query = message.text
    
    if query.lower() in ['отмена', 'стоп', 'выход']:
        await message.answer("Поиск отменен.", reply_markup=get_main_menu())
        await state.clear()
        return

    # Уведомление о начале работы
    wait_msg = await message.answer(f"🔎 _Ищу информацию по запросу: {query}..._")
    
    # Запуск поиска
    result = ai_web_search(query)
    
    await wait_msg.delete()
    await message.answer(f"🌐 **Результат поиска:**\n\n{result}")
    
    await message.answer("Ищем что-то еще? (или напишите 'отмена')")