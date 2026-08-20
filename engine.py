"""Pure query evaluation primitives."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cmp_to_key
import re
from typing import Any, Iterable

from ..storage.utils import _MISSING, clone, contains_value, get_path, set_path


class QueryError(ValueError):
    pass


def _compare(actual: Any, expected: Any, operator: str) -> bool:
    if operator == "$exists":
        return bool(expected) == (actual is not _MISSING)
    if actual is _MISSING:
        return operator in {"$ne", "$nin"}
    if operator == "$eq":
        return actual == expected
    if operator == "$ne":
        return actual != expected
    if operator == "$gt":
        return actual > expected
    if operator == "$gte":
        return actual >= expected
    if operator == "$lt":
        return actual < expected
    if operator == "$lte":
        return actual <= expected
    if operator == "$in":
        return any(item in expected for item in actual) if isinstance(actual, (list, tuple, set)) else actual in expected
    if operator == "$nin":
        return all(item not in expected for item in actual) if isinstance(actual, (list, tuple, set)) else actual not in expected
    if operator == "$contains":
        return contains_value(actual, expected)
    if operator == "$all":
        return isinstance(actual, (list, tuple, set)) and all(item in actual for item in expected)
    if operator == "$size":
        return isinstance(actual, (list, tuple, set, str, dict)) and len(actual) == int(expected)
    if operator == "$regex":
        return isinstance(actual, str) and re.search(str(expected), actual) is not None
    raise QueryError(f"unsupported query operator: {operator}")


def matches(document: dict[str, Any], query: dict[str, Any] | None) -> bool:
    if not query:
        return True
    for field, condition in query.items():
        if field == "$and":
            if not isinstance(condition, list) or not all(matches(document, item) for item in condition):
                return False
            continue
        if field == "$or":
            if not isinstance(condition, list) or not any(matches(document, item) for item in condition):
                return False
            continue
        if field == "$not":
            if matches(document, condition):
                return False
            continue
        actual = get_path(document, field, _MISSING)
        if isinstance(condition, dict) and any(str(key).startswith("$") for key in condition):
            for operator, expected in condition.items():
                try:
                    if not _compare(actual, expected, operator):
                        return False
                except TypeError:
                    return False
        elif actual is _MISSING or actual != condition:
            return False
    return True


def project(document: dict[str, Any], fields: Iterable[str] | None) -> dict[str, Any]:
    if not fields:
        return clone(document)
    result: dict[str, Any] = {}
    for field in fields:
        value = get_path(document, field, _MISSING)
        if value is not _MISSING:
            set_path(result, field, clone(value))
    if "_id" in document:
        result.setdefault("_id", document["_id"])
    return result


def _sort_value(document: dict[str, Any], field: str) -> Any:
    value = get_path(document, field, _MISSING)
    return (value is _MISSING, value)


def sort_documents(documents: list[dict[str, Any]], sort: list[tuple[str, str]] | None) -> list[dict[str, Any]]:
    if not sort:
        return documents

    def compare(left: dict[str, Any], right: dict[str, Any]) -> int:
        for field, direction in sort:
            a_missing, a = _sort_value(left, field)
            b_missing, b = _sort_value(right, field)
            if a_missing != b_missing:
                outcome = 1 if a_missing else -1
            elif a == b:
                outcome = 0
            else:
                try:
                    outcome = -1 if a < b else 1
                except TypeError:
                    outcome = -1 if str(a) < str(b) else 1
            if outcome:
                return outcome if direction.lower() != "desc" else -outcome
        return 0

    return sorted(documents, key=cmp_to_key(compare))


@dataclass(frozen=True)
class QueryPlan:
    collection: str
    strategy: str
    index: str | None
    predicates: int
    sort: list[tuple[str, str]]
    limit: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "collection": self.collection,
            "strategy": self.strategy,
            "index": self.index,
            "predicates": self.predicates,
            "sort": [{"field": field, "direction": direction} for field, direction in self.sort],
            "limit": self.limit,
        }
