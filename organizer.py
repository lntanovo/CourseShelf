"""Compatible import for services.organizer."""
import sys
from typing import TYPE_CHECKING
from services import organizer as _implementation
sys.modules[__name__] = _implementation

if TYPE_CHECKING:
    from services.organizer import CATEGORIES as CATEGORIES
    from services.organizer import INVALID_CHARS as INVALID_CHARS
    from services.organizer import RESERVED as RESERVED
    from services.organizer import NOISE as NOISE
    from services.organizer import settings_path as settings_path
    from services.organizer import load_settings as load_settings
    from services.organizer import save_root as save_root
    from services.organizer import save_settings as save_settings
    from services.organizer import safe_name as safe_name
    from services.organizer import build_plan as build_plan
    from services.organizer import preview_paths as preview_paths
    from services.organizer import planned_copy_path as planned_copy_path
    from services.organizer import extract_candidates as extract_candidates
    from services.organizer import _table_course_lines as _table_course_lines
    from services.organizer import _engine as _engine
    from services.organizer import _engine_lock as _engine_lock
    from services.organizer import ocr_engine as ocr_engine
    from services.organizer import local_ocr as local_ocr
