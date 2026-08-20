"""Versioned binary framing with JSON payloads for low-round-trip clients.

The transport is deliberately simple to audit: a four-byte big-endian frame
length followed by a UTF-8 JSON envelope. The envelope is versioned and carries
a request ID so multiplexing can be added without changing the message shape.
"""

from __future__ import annotations

import json
import socket
import socketserver
import struct
import threading
import uuid
from typing import Any

from ..storage.engine import ConflictError, Database, DuplicateKeyError
from ..query.engine import QueryError

PROTOCOL_VERSION = 1
MAX_FRAME = 8 * 1024 * 1024


class ProtocolError(RuntimeError):
    pass


def encode_frame(message: dict[str, Any]) -> bytes:
    envelope = {"version": PROTOCOL_VERSION, **message}
    body = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_FRAME:
        raise ProtocolError("frame exceeds maximum size")
    return struct.pack(">I", len(body)) + body


def recv_exact(stream: Any, length: int) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.recv(remaining)
        if not chunk:
            raise EOFError("connection closed while receiving a frame")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def decode_frame(stream: Any) -> dict[str, Any]:
    header = recv_exact(stream, 4)
    (length,) = struct.unpack(">I", header)
    if length <= 0 or length > MAX_FRAME:
        raise ProtocolError("invalid frame length")
    try:
        message = json.loads(recv_exact(stream, length).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid JSON frame") from exc
    if not isinstance(message, dict) or message.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported protocol version")
    return message


class ProtocolDispatcher:
    def __init__(self, database: Database) -> None:
        self.database = database

    def dispatch(self, message: dict[str, Any]) -> dict[str, Any]:
        operation = message.get("op")
        collection_name = message.get("collection")
        collection = self.database.collection(collection_name) if collection_name else None
        if operation == "ping":
            return {"ok": True, "result": {"service": "efortablejd", "protocol": PROTOCOL_VERSION}}
        if operation == "status":
            return {"ok": True, "result": self.database.inspect()}
        if operation == "metrics":
            return {"ok": True, "result": self.database.metrics()}
        if collection is None:
            raise ProtocolError("collection is required for this operation")
        if operation == "insert":
            return {"ok": True, "result": collection.add(message["document"], document_id=message.get("document_id"))}
        if operation == "find":
            return {"ok": True, "result": collection.find(message.get("query", {}), projection=message.get("projection"), sort=message.get("sort"), limit=message.get("limit"), cursor=message.get("cursor"), as_of=message.get("as_of"))}
        if operation == "update":
            return {"ok": True, "result": collection.update(message.get("query", {}), message.get("changes", {}), multi=bool(message.get("multi")), upsert=bool(message.get("upsert")), expected_version=message.get("expected_version"))}
        if operation == "delete":
            return {"ok": True, "result": collection.delete(message.get("query", {}), multi=bool(message.get("multi")))}
        if operation == "aggregate":
            return {"ok": True, "result": collection.aggregate(message.get("pipeline", []), as_of=message.get("as_of"))}
        if operation == "create_index":
            if "fields" in message:
                result = collection.create_composite_index(message["fields"], unique=bool(message.get("unique")))
            else:
                result = collection.create_index(message["field"], unique=bool(message.get("unique")))
            return {"ok": True, "result": result}
        raise ProtocolError(f"unsupported operation: {operation}")


class _ProtocolHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        dispatcher: ProtocolDispatcher = self.server.dispatcher  # type: ignore[attr-defined]
        while True:
            try:
                request = decode_frame(self.request)
            except EOFError:
                return
            except Exception as exc:
                self.request.sendall(encode_frame({"request_id": None, "ok": False, "error": str(exc)}))
                return
            request_id = request.get("request_id")
            try:
                response = dispatcher.dispatch(request)
                response["request_id"] = request_id
            except (ConflictError, DuplicateKeyError) as exc:
                response = {"request_id": request_id, "ok": False, "error": str(exc), "code": "conflict"}
            except (KeyError, QueryError, TypeError, ValueError, ProtocolError) as exc:
                response = {"request_id": request_id, "ok": False, "error": str(exc), "code": "invalid_request"}
            except Exception as exc:  # pragma: no cover - transport safety boundary
                response = {"request_id": request_id, "ok": False, "error": "internal server error", "code": "internal"}
            self.request.sendall(encode_frame(response))


class EflortableJDProtocolServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], database: Database) -> None:
        super().__init__(address, _ProtocolHandler)
        self.dispatcher = ProtocolDispatcher(database)
        self.database = database

    def close(self) -> None:
        self.shutdown()
        self.server_close()
        self.database.close()


class DatabaseClient:
    """Small synchronous client with bounded retries for idempotent reads."""

    def __init__(self, host: str = "127.0.0.1", port: int = 7701, *, timeout: float = 3.0, retries: int = 2) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.retries = max(0, retries)
        self._socket: socket.socket | None = None
        self._lock = threading.Lock()

    def connect(self) -> "DatabaseClient":
        if self._socket is None:
            self._socket = socket.create_connection((self.host, self.port), timeout=self.timeout)
            self._socket.settimeout(self.timeout)
        return self

    def close(self) -> None:
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def __enter__(self) -> "DatabaseClient":
        return self.connect()

    def __exit__(self, *_: Any) -> None:
        self.close()

    def call(self, operation: str, *, idempotent: bool = False, **arguments: Any) -> Any:
        attempts = self.retries + 1 if idempotent else 1
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                with self._lock:
                    self.connect()
                    assert self._socket is not None
                    request = {"request_id": uuid.uuid4().hex, "op": operation, **arguments}
                    self._socket.sendall(encode_frame(request))
                    response = decode_frame(self._socket)
                if not response.get("ok"):
                    raise ProtocolError(response.get("error", "request failed"))
                return response.get("result")
            except (OSError, EOFError, ProtocolError) as exc:
                last_error = exc
                self.close()
                if attempt + 1 >= attempts:
                    raise
        raise last_error or ProtocolError("request failed")

    def ping(self) -> dict[str, Any]:
        return self.call("ping", idempotent=True)

    def find(self, collection: str, query: dict[str, Any] | None = None, **options: Any) -> list[dict[str, Any]]:
        return self.call("find", collection=collection, query=query or {}, idempotent=True, **options)

    def insert(self, collection: str, document: dict[str, Any], *, document_id: str | None = None) -> dict[str, Any]:
        return self.call("insert", collection=collection, document=document, document_id=document_id)


def serve_protocol(path: str, host: str = "127.0.0.1", port: int = 7701) -> None:
    server = EflortableJDProtocolServer((host, port), Database(path))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
