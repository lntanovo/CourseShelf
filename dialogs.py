"""Compatible import for ui.dialogs."""
import sys
from ui import dialogs as _implementation
sys.modules[__name__] = _implementation
