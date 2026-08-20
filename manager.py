"""Verified backup and point-in-time recovery utilities."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any

from ..storage.engine import Database
from ..storage.snapshot import read_snapshot, write_snapshot

BACKUP_VERSION = 1


class BackupError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BackupManager:
    def create(self, database: Database, destination: str | Path) -> Path:
        destination = Path(destination)
        if destination.exists() and any(destination.iterdir()):
            raise BackupError(f"backup destination is not empty: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        database.backup(destination)
        files = {}
        for name in ("snapshot.json", "wal.log"):
            path = destination / name
            if path.exists():
                files[name] = {"bytes": path.stat().st_size, "sha256": _sha256(path)}
        manifest = {"version": BACKUP_VERSION, "created_at": time.time(), "sequence": database.sequence, "files": files}
        manifest["manifest_sha256"] = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        manifest_path = destination / "manifest.json"
        temporary = destination / "manifest.json.tmp"
        temporary.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, manifest_path)
        return destination

    def verify(self, backup: str | Path) -> dict[str, Any]:
        backup = Path(backup)
        manifest_path = backup / "manifest.json"
        if not manifest_path.exists():
            raise BackupError("backup is missing manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_manifest_hash = manifest.pop("manifest_sha256", None)
        actual_manifest_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        if manifest.get("version") != BACKUP_VERSION or expected_manifest_hash != actual_manifest_hash:
            raise BackupError("backup manifest checksum or version is invalid")
        for name, spec in manifest["files"].items():
            path = backup / name
            if not path.exists() or path.stat().st_size != int(spec["bytes"]) or _sha256(path) != spec["sha256"]:
                raise BackupError(f"backup file failed verification: {name}")
        read_snapshot(backup / "snapshot.json")
        return {"ok": True, "sequence": manifest["sequence"], "files": manifest["files"]}

    def restore(self, backup: str | Path, destination: str | Path) -> Path:
        backup = Path(backup)
        destination = Path(destination)
        self.verify(backup)
        if destination.exists() and any(destination.iterdir()):
            raise BackupError(f"restore destination is not empty: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        for name in ("snapshot.json", "wal.log"):
            source = backup / name
            if source.exists():
                shutil.copy2(source, destination / name)
        return destination

    def point_in_time_restore(self, backup: str | Path, destination: str | Path, sequence: int) -> Path:
        if sequence < 0:
            raise ValueError("sequence cannot be negative")
        backup = Path(backup)
        destination = Path(destination)
        self.verify(backup)
        if destination.exists() and any(destination.iterdir()):
            raise BackupError(f"restore destination is not empty: {destination}")
        destination.mkdir(parents=True, exist_ok=True)
        snapshot_sequence, collections = read_snapshot(backup / "snapshot.json")
        if sequence > snapshot_sequence:
            raise BackupError(f"requested sequence {sequence} exceeds backup sequence {snapshot_sequence}")
        materialized: dict[str, dict[str, Any]] = {}
        for name, state in collections.items():
            documents: dict[str, dict[str, Any]] = {}
            history = state.get("history", {})
            for identifier, entries in history.items():
                candidates = [entry for entry in entries if int(entry.get("seq", 0)) <= sequence]
                if not candidates:
                    continue
                latest = max(candidates, key=lambda entry: int(entry.get("seq", 0)))
                if latest.get("document") is not None:
                    documents[identifier] = latest["document"]
            materialized[name] = {"documents": documents, "history": history, "indexes": state.get("indexes", [])}
        write_snapshot(destination / "snapshot.json", sequence, materialized)
        (destination / "wal.log").write_bytes(b"")
        return destination
