"""Compatible import for services.inbox."""
import sys
from typing import TYPE_CHECKING
from services import inbox as _implementation
sys.modules[__name__] = _implementation

if TYPE_CHECKING:
    from services.inbox import linked as linked
    from services.inbox import InboxItem as InboxItem
    from services.inbox import build_inbox as build_inbox
