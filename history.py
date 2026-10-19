"""Compatible import for services.history."""
import sys
from typing import TYPE_CHECKING
from services import history as _implementation
sys.modules[__name__] = _implementation

if TYPE_CHECKING:
    from services.history import history_path as history_path
    from services.history import connect_history as connect_history
    from services.history import record as record
    from services.history import update as update
    from services.history import operations as operations
    from services.history import owned_record as owned_record
    from services.history import manage_file as manage_file
    from services.history import undo as undo
