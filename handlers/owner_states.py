"""FSM состояния для владельца магазина."""

from aiogram.fsm.state import StatesGroup, State


class AddProductStates(StatesGroup):
    """Состояния для добавления товара."""
    choose_category = State()
    choose_brand = State()
    enter_name = State()
    enter_purchase_price = State()
    enter_sale_price = State()
    ask_photos = State()
    upload_photos = State()
    enter_sizes = State()
    enter_quantity_for_size = State()


class AddCategoryBrandStates(StatesGroup):
    """Состояния для добавления категории/бренда."""
    enter_category_name = State()
    enter_brand_name = State()


class DeleteProductStates(StatesGroup):
    """Состояния для удаления товара."""
    choose_category = State()
    choose_brand = State()
    choose_product = State()
    confirm = State()


class DeleteCategoryStates(StatesGroup):
    """Состояния для удаления категории."""
    choose = State()
    confirm = State()


class DeleteBrandStates(StatesGroup):
    """Состояния для удаления бренда."""
    choose = State()
    confirm = State()


class EditProductStates(StatesGroup):
    """Состояния для редактирования товара."""
    choose_category = State()
    choose_brand = State()
    choose_product = State()
    view_product = State() # Просмотр карточки
    
    # Редактирование полей
    edit_price = State()
    edit_description = State()
    
    # Редактирование склада
    choose_size_to_edit = State() # Выбор размера для изменения
    edit_stock_qty = State()      # Ввод нового количества

    wait_for_new_photo = State()
    choose_photo_to_delete = State()


class SupportReplyStates(StatesGroup):
    """Состояния для ответов клиентам."""
    waiting_for_reply = State()


class OrderHistoryStates(StatesGroup):
    """Состояния для истории заказов владельца."""
    waiting_for_date = State()