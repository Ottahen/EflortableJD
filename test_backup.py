import tempfile
import unittest
from pathlib import Path

from efortablejd import Database
from efortablejd.backup import BackupError, BackupManager


class BackupTests(unittest.TestCase):
    def test_verified_backup_restore_and_point_in_time(self):
        manager = BackupManager()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source_path = root / "source"
            backup_path = root / "backup"
            restore_path = root / "restore"
            pit_path = root / "pit"
            with Database(source_path) as db:
                collection = db.collection("items")
                first = collection.add({"value": "before"})
                before_sequence = db.sequence
                collection.update({"_id": first["_id"]}, {"$set": {"value": "after"}})
                manager.create(db, backup_path)
            self.assertTrue(manager.verify(backup_path)["ok"])
            manager.restore(backup_path, restore_path)
            with Database(restore_path) as restored:
                self.assertEqual(restored.collection("items").count(), 1)
                self.assertEqual(restored.collection("items").get(first["_id"])["value"], "after")
            manager.point_in_time_restore(backup_path, pit_path, before_sequence)
            with Database(pit_path) as point_in_time:
                self.assertEqual(point_in_time.collection("items").get(first["_id"])["value"], "before")

    def test_backup_tamper_is_rejected(self):
        manager = BackupManager()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with Database(root / "source") as db:
                db.collection("items").add({"value": 1})
                manager.create(db, root / "backup")
            snapshot = root / "backup" / "snapshot.json"
            snapshot.write_text(snapshot.read_text(encoding="utf-8") + "x", encoding="utf-8")
            with self.assertRaises(BackupError):
                manager.verify(root / "backup")


if __name__ == "__main__":
    unittest.main()
