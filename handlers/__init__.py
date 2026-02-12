from .client import client_router
from .owner_products import product_router
from .owner_main import main_router
from .ai import ai_router
from .admin import admin_router
from .owner_warehouse import warehouse_router

__all__ = [
    "client_router",
    "product_router",
    "main_router",
    "ai_router",
    "admin_router",
    "warehouse_router"
]