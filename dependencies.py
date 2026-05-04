import importlib
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_IMPORT_CACHE: Dict[str, Any] = {}
_IMPORT_ERRORS: Dict[str, str] = {}


def is_available(module_name: str) -> bool:
    if module_name in _IMPORT_CACHE:
        return _IMPORT_CACHE[module_name] is not None
    try:
        mod = importlib.import_module(module_name)
        _IMPORT_CACHE[module_name] = mod
        return True
    except ImportError as e:
        _IMPORT_CACHE[module_name] = None
        _IMPORT_ERRORS[module_name] = str(e)
        return False


def get_module(module_name: str) -> Optional[Any]:
    if module_name in _IMPORT_CACHE:
        return _IMPORT_CACHE[module_name]
    try:
        mod = importlib.import_module(module_name)
        _IMPORT_CACHE[module_name] = mod
        return mod
    except ImportError as e:
        _IMPORT_CACHE[module_name] = None
        _IMPORT_ERRORS[module_name] = str(e)
        return None


def get_attr(module_name: str, attr_name: str) -> Optional[Any]:
    mod = get_module(module_name)
    if mod is None:
        return None
    return getattr(mod, attr_name, None)


def require(module_name: str) -> Any:
    mod = get_module(module_name)
    if mod is None:
        error = _IMPORT_ERRORS.get(module_name, "unknown error")
        raise ImportError(f"Required module '{module_name}' is not available: {error}")
    return mod


def get_import_error(module_name: str) -> Optional[str]:
    return _IMPORT_ERRORS.get(module_name)


def clear_cache() -> None:
    _IMPORT_CACHE.clear()
    _IMPORT_ERRORS.clear()
