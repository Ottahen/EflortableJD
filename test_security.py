import json
import tempfile
import unittest
from pathlib import Path

from efortablejd.security import AuditLogger, AuthorizationError, CredentialStore, Principal, RateLimitError, RateLimiter, SecurityManager, verify_secret


class SecurityTests(unittest.TestCase):
    def test_hashed_password_and_revocable_token(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "credentials.json"
            store = CredentialStore(path)
            store.create_user("alex", "correct horse", tenant="tenant-a", roles=["writer"])
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("correct horse", raw)
            principal = store.authenticate_password("alex", "correct horse")
            token = store.issue_token(principal, ttl_seconds=60)
            self.assertEqual(store.authenticate_token(token).tenant, "tenant-a")
            store.revoke_token(token)
            with self.assertRaises(PermissionError):
                store.authenticate_token(token)

    def test_rbac_tenant_isolation_and_rate_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            security = SecurityManager(Path(directory) / "credentials.json")
            principal = Principal("alex", "tenant-a", frozenset({"reader"}))
            security.authorize(principal, "read", "users")
            with self.assertRaises(AuthorizationError):
                security.authorize(principal, "write", "users")
            self.assertEqual(security.scoped_collection(principal, "users"), "tenant-a/users")
            limiter = RateLimiter(capacity=1, refill_per_second=0)
            limiter.check("alex")
            with self.assertRaises(RateLimitError):
                limiter.check("alex")

    def test_audit_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "audit.log"
            logger = AuditLogger(path)
            principal = Principal("alex", "tenant-a", frozenset({"writer"}))
            logger.record(principal=principal, action="insert", resource="users", outcome="success")
            logger.record(principal=principal, action="find", resource="users", outcome="success")
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[1]["previous_hash"], records[0]["hash"])
            with self.assertRaises(ValueError):
                path.write_text(path.read_text(encoding="utf-8") + "corrupted\n", encoding="utf-8")
                AuditLogger(path)


if __name__ == "__main__":
    unittest.main()
