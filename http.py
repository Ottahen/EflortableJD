"""HTTP/JSON transport for EflortableJD."""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from ..storage.engine import ConflictError, Database, DuplicateKeyError
from ..query.engine import QueryError
from ..security import AuditLogger, AuthenticationError, AuthorizationError, Principal, RateLimitError, RateLimiter, SecurityManager
from ..observability import prometheus


class APIError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


def _json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class _Handler(BaseHTTPRequestHandler):
    server_version = "EflortableJD/0.1"

    @property
    def database(self) -> Database:
        return self.server.database  # type: ignore[attr-defined]

    @property
    def auth_token(self) -> str | None:
        return self.server.auth_token  # type: ignore[attr-defined]

    @property
    def security(self) -> SecurityManager | None:
        return self.server.security  # type: ignore[attr-defined]

    @property
    def principal(self) -> Principal | None:
        return getattr(self, "_principal", None)

    @property
    def rate_limiter(self) -> RateLimiter | None:
        return self.server.rate_limiter  # type: ignore[attr-defined]

    @property
    def audit_logger(self) -> AuditLogger | None:
        return self.server.audit_logger  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        if os.environ.get("EFDB_HTTP_LOG", "1") != "0":
            super().log_message(format, *args)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if self.security is not None:
            try:
                self._principal = self.security.authenticate_bearer(header.removeprefix("Bearer ").strip())
                return True
            except AuthenticationError:
                return False
        if not self.auth_token:
            return True
        return header == f"Bearer {self.auth_token}"

    def _send(self, status: int, payload: Any) -> None:
        content_type = "application/json; charset=utf-8"
        if isinstance(payload, dict) and payload.get("content_type") and "body" in payload:
            content_type = str(payload["content_type"])
            encoded = str(payload["body"]).encode("utf-8")
        else:
            encoded = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(encoded)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8 * 1024 * 1024:
                raise APIError(413, "request body exceeds 8 MiB")
            body = self.rfile.read(length)
            value = json.loads(body.decode("utf-8")) if body else {}
            if not isinstance(value, dict):
                raise APIError(400, "request body must be a JSON object")
            return value
        except APIError:
            raise
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise APIError(400, "request body is not valid JSON") from exc

    def _route(self) -> tuple[list[str], dict[str, list[str]]]:
        parsed = urlparse(self.path)
        parts = [unquote(part) for part in parsed.path.split("/") if part]
        return parts, parse_qs(parsed.query)

    def _query_options(self, params: dict[str, list[str]]) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            query = json.loads(params.get("query", ["{}"])[0])
            if not isinstance(query, dict):
                raise ValueError
            projection = json.loads(params["projection"][0]) if "projection" in params else None
            sort = json.loads(params["sort"][0]) if "sort" in params else None
            limit = int(params["limit"][0]) if "limit" in params else None
            cursor = params.get("cursor", [None])[0]
            as_of = int(params["as_of"][0]) if "as_of" in params else None
            options = {"projection": projection, "sort": sort, "limit": limit, "cursor": cursor, "as_of": as_of}
            return query, options
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise APIError(400, "query, projection, sort, and limit parameters must be valid JSON values") from exc

    def _dispatch(self) -> tuple[int, Any]:
        parts, params = self._route()
        if self.command == "GET" and parts == ["health"]:
            return 200, {"ok": True, "service": "efortablejd", "version": "1"}
        if self.command == "GET" and parts == ["v1", "status"]:
            return 200, {"ok": True, **self.database.inspect()}
        if self.command == "GET" and parts == ["v1", "metrics"]:
            return 200, self.database.metrics()
        if self.command == "GET" and parts == ["v1", "metrics", "prometheus"]:
            return 200, {"content_type": "text/plain; version=0.0.4", "body": prometheus(self.database.metrics())}
        if self.command == "GET" and parts == ["v1", "inspect"]:
            return 200, self.database.inspect()
        if self.command == "POST" and parts == ["v1", "checkpoint"]:
            self.database.checkpoint()
            return 200, {"ok": True, "sequence": self.database.metrics()["last_sequence"]}
        if self.command == "POST" and parts == ["v1", "compact"]:
            return 200, {"ok": True, **self.database.compact()}
        if len(parts) >= 2 and parts[0] == "v1":
            logical_collection = parts[1]
            if self.security is not None:
                if self.principal is None:
                    raise APIError(401, "authentication required")
                action = "read" if self.command == "GET" else ("admin" if parts[-1] in {"_index", "_explain", "_aggregate"} else "write")
                self.security.authorize(self.principal, action, logical_collection)
                collection_name = self.security.scoped_collection(self.principal, logical_collection)
            else:
                collection_name = logical_collection
            collection = self.database.collection(collection_name)
            if len(parts) == 2 and self.command == "GET":
                query, options = self._query_options(params)
                return 200, {"data": collection.find(query, **options), "count": collection.count(query)}
            if len(parts) == 2 and self.command == "POST" and params.get("aggregate") != ["1"]:
                body = self._read_json()
                document = body.get("document", body)
                created = collection.add(document, document_id=body.get("_id") if "document" in body else None)
                return 201, {"data": created}
            if len(parts) == 2 and self.command == "POST" and parts[1] and params.get("aggregate") == ["1"]:
                body = self._read_json()
                return 200, {"data": collection.aggregate(body.get("pipeline", []), as_of=body.get("as_of"))}
            if len(parts) == 2 and self.command == "PATCH":
                body = self._read_json()
                updated = collection.update(body.get("query", {}), body.get("changes", {}), multi=bool(body.get("multi")), upsert=bool(body.get("upsert")), expected_version=body.get("expected_version"))
                return 200, {"data": updated, "count": len(updated)}
            if len(parts) == 2 and self.command == "DELETE":
                body = self._read_json()
                deleted = collection.delete(body.get("query", {}), multi=bool(body.get("multi")))
                return 200, {"deleted": deleted}
            if len(parts) == 3 and parts[2] == "_aggregate" and self.command == "POST":
                body = self._read_json()
                return 200, {"data": collection.aggregate(body.get("pipeline", []), as_of=body.get("as_of"))}
            if len(parts) == 3 and parts[2] == "_index" and self.command == "POST":
                body = self._read_json()
                if "fields" in body:
                    index = collection.create_composite_index(body["fields"], unique=bool(body.get("unique")))
                else:
                    index = collection.create_index(body["field"], unique=bool(body.get("unique")))
                return 201, {"index": index}
            if len(parts) == 3 and parts[2] == "_explain" and self.command == "POST":
                body = self._read_json()
                return 200, collection.explain(body.get("query", {}), sort=body.get("sort"), limit=body.get("limit"))
            if len(parts) == 3 and self.command == "GET":
                document = collection.get(parts[2])
                if document is None:
                    raise APIError(404, "document not found")
                return 200, {"data": document}
            if len(parts) == 3 and self.command == "PATCH":
                body = self._read_json()
                updated = collection.update({"_id": parts[2]}, body.get("changes", body), expected_version=body.get("expected_version"))
                if not updated:
                    raise APIError(404, "document not found")
                return 200, {"data": updated[0]}
            if len(parts) == 3 and self.command == "DELETE":
                deleted = collection.delete({"_id": parts[2]})
                if not deleted:
                    raise APIError(404, "document not found")
                return 200, {"deleted": deleted}
        raise APIError(404, "route not found")

    def _handle(self) -> None:
        try:
            if self.rate_limiter is not None:
                self.rate_limiter.check(self.client_address[0])
            if not self._authorized():
                if self.audit_logger:
                    self.audit_logger.record(principal=self.principal, action=self.command, resource=self.path, outcome="denied")
                self._send(401, {"error": "missing or invalid bearer token"})
                return
            status, payload = self._dispatch()
            if self.audit_logger:
                self.audit_logger.record(principal=self.principal, action=self.command, resource=self.path, outcome="success", metadata={"status": status})
            self._send(status, payload)
        except APIError as exc:
            self._send(exc.status, {"error": str(exc)})
        except (ConflictError, DuplicateKeyError) as exc:
            if self.audit_logger:
                self.audit_logger.record(principal=self.principal, action=self.command, resource=self.path, outcome="conflict", metadata={"error": str(exc)})
            self._send(409, {"error": str(exc)})
        except RateLimitError as exc:
            self._send(429, {"error": str(exc)})
        except (AuthenticationError, AuthorizationError) as exc:
            if self.audit_logger:
                self.audit_logger.record(principal=self.principal, action=self.command, resource=self.path, outcome="denied", metadata={"error": str(exc)})
            self._send(403, {"error": str(exc)})
        except (KeyError, QueryError, TypeError, ValueError) as exc:
            self.database._metrics["errors"] += 1
            self._send(400, {"error": str(exc)})
        except Exception as exc:  # pragma: no cover - final safety boundary
            self.database._metrics["errors"] += 1
            self._send(500, {"error": "internal server error", "detail": str(exc)})

    do_GET = _handle
    do_POST = _handle
    do_PATCH = _handle
    do_DELETE = _handle


class EflortableJDServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], database: Database, *, auth_token: str | None = None, security: SecurityManager | None = None, rate_limiter: RateLimiter | None = None, audit_logger: AuditLogger | None = None) -> None:
        super().__init__(address, _Handler)
        self.database = database
        self.auth_token = auth_token
        self.security = security
        self.rate_limiter = rate_limiter
        self.audit_logger = audit_logger

    def close(self) -> None:
        self.shutdown()
        super().server_close()
        self.database.close()


def serve(path: str, host: str = "127.0.0.1", port: int = 7700, *, auth_token: str | None = None) -> None:
    database = Database(path)
    credentials_path = os.environ.get("EFDB_CREDENTIALS")
    security = SecurityManager(credentials_path) if credentials_path else None
    rate_limiter = RateLimiter(int(os.environ.get("EFDB_RATE_CAPACITY", "100")), float(os.environ.get("EFDB_RATE_REFILL", "25"))) if security else None
    audit_logger = AuditLogger(os.environ.get("EFDB_AUDIT_LOG", str(Path(path) / "audit.log"))) if security else None
    server = EflortableJDServer((host, port), database, auth_token=auth_token, security=security, rate_limiter=rate_limiter, audit_logger=audit_logger)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.close()
