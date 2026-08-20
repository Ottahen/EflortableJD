"""Explicit hash indexes for equality and composite-key lookups."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from ..storage.utils import _MISSING, get_path


class UniqueConstraintError(ValueError):
    pass


class _BaseHashIndex:
    def __init__(self, *, unique: bool = False) -> None:
        self.unique = unique
        self._values: dict[Any, set[str]] = defaultdict(set)

    def _key(self, value: Any) -> Any:
        if isinstance(value, (dict, list, set)):
            return repr(value)
        try:
            hash(value)
            return value
        except TypeError:
            return repr(value)

    def _add_key(self, key: Any, document_id: str) -> None:
        normalized = self._key(key)
        existing = self._values[normalized] - {document_id}
        if self.unique and existing:
            raise UniqueConstraintError(f"duplicate value for unique index {self.label}: {key!r}")
        self._values[normalized].add(document_id)

    def _remove_key(self, key: Any, document_id: str) -> None:
        normalized = self._key(key)
        ids = self._values.get(normalized)
        if ids is None:
            return
        ids.discard(document_id)
        if not ids:
            self._values.pop(normalized, None)

    def lookup(self, value: Any) -> set[str]:
        return set(self._values.get(self._key(value), set()))


class HashIndex(_BaseHashIndex):
    def __init__(self, field: str, *, unique: bool = False) -> None:
        super().__init__(unique=unique)
        self.field = field
        self.label = field

    def add(self, document: dict[str, Any]) -> None:
        value = get_path(document, self.field, _MISSING)
        if value is not _MISSING:
            self._add_key(value, str(document["_id"]))

    def remove(self, document: dict[str, Any]) -> None:
        value = get_path(document, self.field, _MISSING)
        if value is not _MISSING:
            self._remove_key(value, str(document["_id"]))

    def export(self) -> dict[str, Any]:
        return {"field": self.field, "unique": self.unique}


class CompositeHashIndex(_BaseHashIndex):
    def __init__(self, fields: Iterable[str], *, unique: bool = False) -> None:
        super().__init__(unique=unique)
        self.fields = tuple(fields)
        if not self.fields:
            raise ValueError("composite index requires at least one field")
        self.label = ",".join(self.fields)

    def _value(self, document: dict[str, Any]) -> tuple[Any, ...] | object:
        values = tuple(get_path(document, field, _MISSING) for field in self.fields)
        return _MISSING if any(value is _MISSING for value in values) else values

    def add(self, document: dict[str, Any]) -> None:
        value = self._value(document)
        if value is not _MISSING:
            self._add_key(value, str(document["_id"]))

    def remove(self, document: dict[str, Any]) -> None:
        value = self._value(document)
        if value is not _MISSING:
            self._remove_key(value, str(document["_id"]))

    def lookup_fields(self, values: Iterable[Any]) -> set[str]:
        return self.lookup(tuple(values))

    def export(self) -> dict[str, Any]:
        return {"fields": list(self.fields), "unique": self.unique}


class IndexManager:
    def __init__(self) -> None:
        self._indexes: dict[str, HashIndex] = {}
        self._composites: dict[tuple[str, ...], CompositeHashIndex] = {}

    def create(self, field: str, *, unique: bool = False, documents: list[dict[str, Any]] | None = None) -> HashIndex:
        if field in self._indexes:
            return self._indexes[field]
        index = HashIndex(field, unique=unique)
        for document in documents or []:
            index.add(document)
        self._indexes[field] = index
        return index

    def create_composite(self, fields: Iterable[str], *, unique: bool = False, documents: list[dict[str, Any]] | None = None) -> CompositeHashIndex:
        key = tuple(fields)
        if key in self._composites:
            return self._composites[key]
        index = CompositeHashIndex(key, unique=unique)
        for document in documents or []:
            index.add(document)
        self._composites[key] = index
        return index

    def drop(self, field: str) -> bool:
        return self._indexes.pop(field, None) is not None

    def drop_composite(self, fields: Iterable[str]) -> bool:
        return self._composites.pop(tuple(fields), None) is not None

    def get(self, field: str) -> HashIndex | None:
        return self._indexes.get(field)

    def get_composite(self, fields: Iterable[str]) -> CompositeHashIndex | None:
        return self._composites.get(tuple(fields))

    def all(self) -> list[HashIndex | CompositeHashIndex]:
        return [*self._indexes.values(), *self._composites.values()]

    def export(self) -> list[dict[str, Any]]:
        return [index.export() for index in self.all()]
