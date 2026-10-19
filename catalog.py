"""Compatible import for services.catalog."""
import sys
from services import catalog as _implementation
sys.modules[__name__] = _implementation
