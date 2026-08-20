import tempfile
import unittest
from pathlib import Path

from efortablejd import Database, DuplicateKeyError
from efortablejd.storage.engine import BatchError
from efortablejd.storage.snapshot import SnapshotCorruptionError
from efortablejd.storage.wal import WALCorruptionError


class StorageHardeningTests(unittest.TestCase):
    def test_batch_is_atomic_and_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            with Database(directory) as db:
                collection = db.collection("items")
                first = collection.add({"key": "existing"})
                with self.assertRaises(BatchError):
                    db.batch([
                        {"op": "insert", "collection": "items", "document": {"_id": "new", "key": "ok"}},
                        {"op": "replace", "collection": "items", "document": {"_id": "missing", "key": "bad"}},
                    ])
                self.assertEqual(collection.count(), 1)
                self.assertEqual(collection.get(first["_id"])["key"], "existing")

    def test_mvcc_historical_read_and_compaction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with Database(path) as db:
                collection = db.collection("items")
                first = collection.add({"value": "before"})
                first_sequence = db.sequence
                collection.update({"_id": first["_id"]}, {"$set": {"value": "after"}})
                self.assertEqual(collection.get(first["_id"], as_of=first_sequence)["value"], "before")
                self.assertEqual(collection.get(first["_id"])["value"], "after")
                result = db.compact()
                self.assertEqual(result["wal_bytes_after"], 0)
            with Database(path) as reopened:
                self.assertEqual(reopened.collection("items").get(first["_id"], as_of=first_sequence)["value"], "before")

    def test_corrupt_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with Database(path) as db:
                db.collection("items").add({"value": 1})
                db.checkpoint()
            snapshot = path / "snapshot.json"
            snapshot.write_text(snapshot.read_text(encoding="utf-8").replace("items", "corrupted", 1), encoding="utf-8")
            with self.assertRaises(SnapshotCorruptionError):
                Database(path)

    def test_middle_wal_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            with Database(path) as db:
                db.collection("items").add({"value": 1})
                db.collection("items").add({"value": 2})
                db.collection("items").add({"value": 3})
            wal = path / "wal.log"
            lines = wal.read_bytes().splitlines(keepends=True)
            wal.write_bytes(lines[0] + b"not-json\n" + lines[2])
            with self.assertRaises(WALCorruptionError):
                Database(path)


if __name__ == "__main__":
    unittest.main()
