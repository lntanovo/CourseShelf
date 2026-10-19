"""Compatible import for services.library_index."""
import sys
from services import library_index as _implementation
sys.modules[__name__] = _implementation
