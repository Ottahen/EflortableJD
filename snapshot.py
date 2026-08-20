"""Versioned atomic snapshots for the local storage engine."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .utils import canonical_json

SNAPSHOT_VERSION = 1


class SnapshotCorruptionError(RuntimeError):
    pass


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def write_snapshot(path: str | Path, sequence: int, collections: dict[str, dict[str, dict[str, Any]]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": SNAPSHOT_VERSION, "seq": sequence, "collections": collections}
    record = {"payload": payload, "sha256": _digest(payload)}
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    try:
        directory_fd = os.open(str(target.parent), os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        # Directory fsync is not available on every supported filesystem.
        pass


def read_snapshot(path: str | Path) -> tuple[int, dict[str, dict[str, dict[str, Any]]]]:
    target = Path(path)
    if not target.exists():
        return 0, {}
    try:
        with target.open("r", encoding="utf-8") as handle:
            record = json.load(handle)
        payload = record["payload"]
        if payload.get("version") != SNAPSHOT_VERSION or record.get("sha256") != _digest(payload):
            raise SnapshotCorruptionError("snapshot version or checksum is invalid")
        return int(payload["seq"]), dict(payload["collections"])
    except SnapshotCorruptionError:
        raise
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise SnapshotCorruptionError(f"cannot read snapshot {target}") from exc
