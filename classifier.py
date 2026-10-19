"""Compatible import for services.classifier."""
import sys
from services import classifier as _implementation
sys.modules[__name__] = _implementation
