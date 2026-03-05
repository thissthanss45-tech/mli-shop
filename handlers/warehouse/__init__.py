from .common import warehouse_router

# Import modules to register handlers on shared router
from . import dashboard  # noqa: F401
from . import procurement  # noqa: F401
from . import reports  # noqa: F401
from . import product_card  # noqa: F401

__all__ = ["warehouse_router"]
