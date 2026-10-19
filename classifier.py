"""Compatible import for services.classifier."""
import sys
from typing import TYPE_CHECKING
from services import classifier as _implementation
sys.modules[__name__] = _implementation

if TYPE_CHECKING:
    from services.classifier import _normal as _normal
    from services.classifier import Suggestion as Suggestion
    from services.classifier import KEYWORDS as KEYWORDS
    from services.classifier import suggest as suggest
