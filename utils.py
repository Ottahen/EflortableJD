"""Small deterministic helpers shared by storage and query code."""

from __future__ import annotations

import copy
import json
from typing import Any

_MISSING = object()


def clone(value: Any) -> Any:
    return copy.deepcopy(value)


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def get_path(document: dict[str, Any], path: str, default: Any = _MISSING) -> Any:
    current: Any = document
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            if default is _MISSING:
                return _MISSING
            return default
    return current


def set_path(document: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    current = document
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def del_path(document: dict[str, Any], path: str) -> bool:
    parts = path.split(".")
    current: Any = document
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return isinstance(current, dict) and current.pop(parts[-1], _MISSING) is not _MISSING


def contains_value(actual: Any, expected: Any) -> bool:
    if isinstance(actual, (list, tuple, set)):
        return expected in actual
    if isinstance(actual, str):
        return str(expected) in actual
    if isinstance(actual, dict):
        return expected in actual or expected in actual.values()
    return False
