"""Compatible import for services.file_ops."""
import sys
from typing import TYPE_CHECKING
from services import file_ops as _implementation
sys.modules[__name__] = _implementation

if TYPE_CHECKING:
    from services.file_ops import log as log
    from services.file_ops import Cancelled as Cancelled
    from services.file_ops import PartialMoveError as PartialMoveError
    from services.file_ops import _sha256 as _sha256
    from services.file_ops import transfer as transfer
