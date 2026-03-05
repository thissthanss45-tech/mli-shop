"""Совместимый фасад owner_main; фактические хендлеры вынесены в owner_main_parts."""

from .owner_main_parts import main_router

__all__ = ["main_router"]
