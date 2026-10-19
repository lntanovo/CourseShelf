"""Compatible import for services.catalog."""
import sys
from typing import TYPE_CHECKING
from services import catalog as _implementation
sys.modules[__name__] = _implementation

if TYPE_CHECKING:
    from services.catalog import CATALOG_NAME as CATALOG_NAME
    from services.catalog import SCHEMA_VERSION as SCHEMA_VERSION
    from services.catalog import log as log
    from services.catalog import _snapshot as _snapshot
    from services.catalog import current_catalog as current_catalog
    from services.catalog import catalog_snapshot as catalog_snapshot
    from services.catalog import _audit as _audit
    from services.catalog import CatalogError as CatalogError
    from services.catalog import _component as _component
    from services.catalog import _key as _key
    from services.catalog import _parts as _parts
    from services.catalog import _root as _root
    from services.catalog import catalog_path as catalog_path
    from services.catalog import load_catalog as load_catalog
    from services.catalog import _read_only as _read_only
    from services.catalog import _migrate as _migrate
    from services.catalog import _validate as _validate
    from services.catalog import writable_catalog as writable_catalog
    from services.catalog import save_catalog as save_catalog
    from services.catalog import _atomic_save as _atomic_save
    from services.catalog import _folder as _folder
    from services.catalog import is_managed as is_managed
    from services.catalog import categories_for as categories_for
    from services.catalog import disk_categories as disk_categories
    from services.catalog import plan_paths as plan_paths
    from services.catalog import create_plan as create_plan
    from services.catalog import import_course as import_course
    from services.catalog import set_aliases as set_aliases
    from services.catalog import aliases_for as aliases_for
    from services.catalog import _checked_category as _checked_category
    from services.catalog import add_category as add_category
    from services.catalog import rename_category as rename_category
    from services.catalog import count_contents as count_contents
    from services.catalog import trash_category as trash_category
    from services.catalog import restore_defaults as restore_defaults
    from services.catalog import managed_paths as managed_paths
    from services.catalog import missing_paths as missing_paths
    from services.catalog import restore_missing as restore_missing
