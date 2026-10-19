"""Compatible import for services.library_index."""
import sys
from typing import TYPE_CHECKING
from services import library_index as _implementation
sys.modules[__name__] = _implementation

if TYPE_CHECKING:
    from services.library_index import index_path as index_path
    from services.library_index import connect_index as connect_index
    from services.library_index import scan as scan
    from services.library_index import search as search
