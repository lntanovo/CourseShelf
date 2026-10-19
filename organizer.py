"""Compatible import for services.organizer."""
import sys
from services import organizer as _implementation
sys.modules[__name__] = _implementation
