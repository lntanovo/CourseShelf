"""Compatible import for services.inbox."""
import sys
from services import inbox as _implementation
sys.modules[__name__] = _implementation
