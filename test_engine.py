import json
import tempfile
import unittest
from pathlib import Path

from efortablejd import Database, DuplicateKeyError
from efortablejd.storage.wal import WALCorruptionError


class EngineTests(unittest.TestCase):
    def test_crud_queries_indexes_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with Database(path) as db:
                users = db.collection("users")
                users.create_index("email", unique=True)
                alex = users.add({"name": "Alex", "email": "alex@example.com", "age": 21, "profile": {"theme": "dark"}})
                users.add({"name": "Sam", "email": "sam@example.com", "age": 16})
                self.assertEqual(users.find({"email": "alex@example.com"})[0]["_id"], alex["_id"])
                self.assertEqual(users.count({"age": {"$gte": 18}}), 1)
                self.assertEqual(users.find({"profile.theme": "dark"})[0]["name"], "Alex")
                self.assertEqual(users.find({}, projection=["name"])[0].keys(), {"_id", "name"})
                self.assertEqual(users.explain({"email": "alex@example.com"})["strategy"], "index_scan")
                with self.assertRaises(DuplicateKeyError):
                    users.add({"name": "Other", "email": "alex@example.com"})
                updated = users.update({"_id": alex["_id"]}, {"$inc": {"age": 1}})[0]
                self.assertEqual(updated["age"], 22)
                self.assertEqual(users.delete({"name": "Sam"}), 1)
                db.checkpoint()
            with Database(path) as reopened:
                users = reopened.collection("users")
                self.assertEqual(users.count(), 1)
                self.assertEqual(users.find({"email": "alex@example.com"})[0]["age"], 22)
                self.assertEqual(users.explain({"email": "alex@example.com"})["strategy"], "index_scan")

    def test_expected_version_conflict(self):
        from efortablejd.storage.engine import ConflictError

        with tempfile.TemporaryDirectory() as directory:
            with Database(directory) as db:
                collection = db.collection("items")
                item = collection.add({"value": 1})
                collection.update({"_id": item["_id"]}, {"$inc": {"value": 1}}, expected_version=item["_version"])
                with self.assertRaises(ConflictError):
                    collection.update({"_id": item["_id"]}, {"$inc": {"value": 1}}, expected_version=item["_version"])

    def test_torn_final_wal_record_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with Database(path) as db:
                db.collection("events").add({"kind": "created"})
            with (path / "wal.log").open("ab") as handle:
                handle.write(b'{"version":1,"seq":99')
            with Database(path) as reopened:
                self.assertEqual(reopened.collection("events").count(), 1)
                self.assertEqual(reopened.metrics()["ignored_torn_wal_records"], 1)

    def test_boolean_and_array_operators(self):
        with tempfile.TemporaryDirectory() as directory:
            with Database(directory) as db:
                collection = db.collection("docs")
                collection.add({"tags": ["a", "b"], "active": True})
                collection.add({"tags": ["b"], "active": False})
                self.assertEqual(collection.count({"tags": {"$contains": "a"}}), 1)
                self.assertEqual(collection.count({"$or": [{"active": True}, {"tags": {"$contains": "a"}}]}), 1)
                self.assertEqual(collection.count({"active": {"$exists": True}}), 2)


if __name__ == "__main__":
    unittest.main()
