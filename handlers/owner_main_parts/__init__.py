from .common import main_router

from . import promo_menu_support  # noqa: F401
from . import catalog_delete  # noqa: F401
from . import orders_stats  # noqa: F401

__all__ = ["main_router"]
