"""The efdb command-line interface."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from ..networking.http import serve
from ..backup import BackupManager
from ..observability import prometheus
from ..security import CredentialStore
from ..storage.engine import Database


def _database(args: argparse.Namespace) -> Database:
    return Database(args.path)


def _print(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def cmd_start(args: argparse.Namespace) -> int:
    print(f"EflortableJD listening on http://{args.host}:{args.port} using {Path(args.path).resolve()}")
    serve(args.path, args.host, args.port, auth_token=args.auth_token or os.environ.get("EFDB_AUTH_TOKEN"))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    with _database(args) as db:
        _print(db.inspect())
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    with _database(args) as db:
        if args.prometheus:
            print(prometheus(db.metrics()), end="")
        else:
            _print(db.metrics())
    return 0


def cmd_compact(args: argparse.Namespace) -> int:
    with _database(args) as db:
        _print(db.compact())
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    with _database(args) as db:
        if args.collection:
            collection = db.collection(args.collection)
            _print({"collection": args.collection, "count": collection.count(), "indexes": collection.indexes.export(), "sample": collection.find(limit=args.sample)})
        else:
            _print(db.inspect())
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    with _database(args) as db:
        collection = db.collection(args.collection)
        _print(collection.explain(json.loads(args.query), sort=json.loads(args.sort) if args.sort else None, limit=args.limit))
    return 0


def cmd_backup(args: argparse.Namespace) -> int:
    with _database(args) as db:
        path = BackupManager().create(db, args.destination)
        _print({"ok": True, "destination": str(path.resolve()), "sequence": db.metrics()["last_sequence"]})
    return 0


def cmd_verify_backup(args: argparse.Namespace) -> int:
    _print(BackupManager().verify(args.backup))
    return 0


def cmd_pitr(args: argparse.Namespace) -> int:
    path = BackupManager().point_in_time_restore(args.backup, args.destination, args.sequence)
    _print({"ok": True, "destination": str(path.resolve()), "sequence": args.sequence})
    return 0


def cmd_user_create(args: argparse.Namespace) -> int:
    password = args.password or getpass.getpass("Password: ")
    CredentialStore(args.credentials).create_user(args.username, password, tenant=args.tenant, roles=args.roles.split(","))
    _print({"ok": True, "username": args.username, "tenant": args.tenant, "roles": args.roles.split(",")})
    return 0


def cmd_restore(args: argparse.Namespace) -> int:
    source = Path(args.source)
    destination = Path(args.path)
    destination.mkdir(parents=True, exist_ok=True)
    if not (source / "snapshot.json").exists():
        raise SystemExit(f"backup is missing snapshot.json: {source}")
    for filename in ("snapshot.json", "wal.log"):
        origin = source / filename
        if origin.exists():
            shutil.copy2(origin, destination / filename)
    _print({"ok": True, "restored_from": str(source.resolve()), "destination": str(destination.resolve())})
    return 0


def cmd_shell(args: argparse.Namespace) -> int:
    print("EflortableJD shell. Enter JSON commands, or 'exit'.")
    with _database(args) as db:
        for line in sys.stdin:
            line = line.strip()
            if line in {"exit", "quit"}:
                break
            if not line:
                continue
            try:
                command = json.loads(line)
                collection = db.collection(command["collection"])
                operation = command.get("operation", "find")
                if operation == "add":
                    result = collection.add(command["document"])
                elif operation == "find":
                    result = collection.find(command.get("query", {}), projection=command.get("projection"), sort=command.get("sort"), limit=command.get("limit"))
                elif operation == "update":
                    result = collection.update(command.get("query", {}), command.get("changes", {}), multi=bool(command.get("multi")))
                elif operation == "delete":
                    result = collection.delete(command.get("query", {}), multi=bool(command.get("multi")))
                else:
                    raise ValueError(f"unknown operation: {operation}")
                _print(result)
            except Exception as exc:
                _print({"error": str(exc)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="efdb", description="EflortableJD document database")
    parser.add_argument("--path", default="./data", help="database directory")
    sub = parser.add_subparsers(dest="command", required=True)

    start = sub.add_parser("start", help="start the HTTP server")
    start.add_argument("--host", default="127.0.0.1")
    start.add_argument("--port", type=int, default=7700)
    start.add_argument("--auth-token")
    start.set_defaults(func=cmd_start)

    for name, function in (("status", cmd_status), ("metrics", cmd_metrics)):
        command = sub.add_parser(name)
        if name == "metrics":
            command.add_argument("--prometheus", action="store_true")
        command.set_defaults(func=function)

    compact = sub.add_parser("compact")
    compact.set_defaults(func=cmd_compact)

    inspect = sub.add_parser("inspect")
    inspect.add_argument("--collection")
    inspect.add_argument("--sample", type=int, default=5)
    inspect.set_defaults(func=cmd_inspect)

    explain = sub.add_parser("explain")
    explain.add_argument("collection")
    explain.add_argument("query", help="query JSON")
    explain.add_argument("--sort")
    explain.add_argument("--limit", type=int)
    explain.set_defaults(func=cmd_explain)

    backup = sub.add_parser("backup")
    backup.add_argument("destination")
    backup.set_defaults(func=cmd_backup)

    verify_backup = sub.add_parser("verify-backup")
    verify_backup.add_argument("backup")
    verify_backup.set_defaults(func=cmd_verify_backup)

    pitr = sub.add_parser("pitr")
    pitr.add_argument("backup")
    pitr.add_argument("destination")
    pitr.add_argument("sequence", type=int)
    pitr.set_defaults(func=cmd_pitr)

    user_create = sub.add_parser("user-create")
    user_create.add_argument("--credentials", required=True)
    user_create.add_argument("--username", required=True)
    user_create.add_argument("--tenant", default="default")
    user_create.add_argument("--roles", default="reader")
    user_create.add_argument("--password")
    user_create.set_defaults(func=cmd_user_create)

    restore = sub.add_parser("restore")
    restore.add_argument("source")
    restore.set_defaults(func=cmd_restore)

    shell = sub.add_parser("shell")
    shell.set_defaults(func=cmd_shell)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
