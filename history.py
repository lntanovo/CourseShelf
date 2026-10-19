"""Compatible import for services.history."""
import sys
from services import history as _implementation
sys.modules[__name__] = _implementation
