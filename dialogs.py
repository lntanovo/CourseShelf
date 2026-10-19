"""Compatible import for ui.dialogs."""
import sys
from typing import TYPE_CHECKING
from ui import dialogs as _implementation
sys.modules[__name__] = _implementation

if TYPE_CHECKING:
    from ui.dialogs import confirmation as confirmation
    from ui.dialogs import confirm as confirm
