"""Checksummed append-only write-ahead log."""

from __future__ import annotations

import json
import os
import zlib
from pathlib import Path
from typing import Any, Callable

from .utils import canonical_json

WAL_VERSION = 1


class WALCorruptionError(RuntimeError):
    pass


class WriteAheadLog:
    def __init__(self, path: str | Path, *, sync: bool = True) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.sync = sync
        self.replayed_records = 0
        self._handle = self.path.open("a+b")

    def close(self) -> None:
        self._handle.close()

    def append(self, sequence: int, operation: str, payload: dict[str, Any]) -> None:
        body = {"version": WAL_VERSION, "seq": sequence, "op": operation, "payload": payload}
        checksum = zlib.crc32(canonical_json(body)) & 0xFFFFFFFF
        record = dict(body)
        record["crc32"] = checksum
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._handle.write(encoded.encode("utf-8") + b"\n")
        self._handle.flush()
        if self.sync:
            os.fsync(self._handle.fileno())

    def replay(self, apply: Callable[[int, str, dict[str, Any]], None]) -> tuple[int, int]:
        """Replay valid records and return (last_sequence, ignored_torn_records)."""
        self._handle.flush()
        self._handle.seek(0)
        last_sequence = 0
        ignored_torn = 0
        self.replayed_records = 0
        lines = self._handle.readlines()
        for index, raw in enumerate(lines):
            if not raw.endswith(b"\n"):
                ignored_torn += 1
                break
            try:
                record = json.loads(raw.decode("utf-8"))
                crc = record.pop("crc32")
                expected = zlib.crc32(canonical_json(record)) & 0xFFFFFFFF
                if record.get("version") != WAL_VERSION or crc != expected:
                    raise WALCorruptionError(f"invalid WAL record at line {index + 1}")
                sequence = int(record["seq"])
                if sequence <= last_sequence:
                    raise WALCorruptionError(f"non-monotonic WAL sequence at line {index + 1}")
                apply(sequence, str(record["op"]), dict(record["payload"]))
                last_sequence = sequence
                self.replayed_records += 1
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                if index == len(lines) - 1:
                    ignored_torn += 1
                    break
                raise WALCorruptionError(f"malformed WAL record at line {index + 1}") from exc
        self._handle.seek(0, os.SEEK_END)
        return last_sequence, ignored_torn

    def truncate(self) -> None:
        """Remove all WAL records after a durable snapshot has been written."""
        self._handle.flush()
        self._handle.seek(0)
        self._handle.truncate(0)
        self._handle.flush()
        if self.sync:
            os.fsync(self._handle.fileno())
        self._handle.seek(0, os.SEEK_END)

    def byte_size(self) -> int:
        self._handle.flush()
        return self.path.stat().st_size if self.path.exists() else 0
