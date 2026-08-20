import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from pathlib import Path

from efortablejd.networking.http import EflortableJDServer
from efortablejd.security import AuditLogger, CredentialStore, RateLimiter, SecurityManager
from efortablejd.storage.engine import Database


class HTTPSecurityTests(unittest.TestCase):
    def test_secure_server_scopes_tenant_and_enforces_roles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            credentials = CredentialStore(root / "credentials.json")
            credentials.create_user("writer", "secret", tenant="tenant-a", roles=["writer"])
            credentials.create_user("reader", "secret", tenant="tenant-a", roles=["reader"])
            security = SecurityManager(root / "credentials.json")
            writer = credentials.authenticate_password("writer", "secret")
            reader = credentials.authenticate_password("reader", "secret")
            writer_token = credentials.issue_token(writer)
            reader_token = credentials.issue_token(reader)
            database = Database(root / "db")
            audit = AuditLogger(root / "audit.log")
            server = EflortableJDServer(("127.0.0.1", 0), database, security=security, rate_limiter=RateLimiter(20, 20), audit_logger=audit)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            try:
                connection = HTTPConnection(host, port, timeout=3)
                connection.request("POST", "/v1/users", body=json.dumps({"name": "Alex"}), headers={"Authorization": f"Bearer {writer_token}", "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                response.read()
                connection.request("POST", "/v1/users", body=json.dumps({"name": "Blocked"}), headers={"Authorization": f"Bearer {reader_token}", "Content-Type": "application/json"})
                response = connection.getresponse()
                self.assertEqual(response.status, 403)
                response.read()
                connection.request("GET", "/v1/users", headers={"Authorization": f"Bearer {reader_token}"})
                response = connection.getresponse()
                self.assertEqual(json.loads(response.read())["count"], 1)
                audit_lines = (root / "audit.log").read_text(encoding="utf-8").splitlines()
                self.assertGreaterEqual(len(audit_lines), 3)
            finally:
                server.shutdown()
                server.server_close()
                database.close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
