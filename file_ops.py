"""Compatible import for services.file_ops."""
import sys
from services import file_ops as _implementation
sys.modules[__name__] = _implementation
