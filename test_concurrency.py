import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from efortablejd import Database


class ConcurrencyTests(unittest.TestCase):
    def test_concurrent_inserts_are_durable_and_unique(self):
        with tempfile.TemporaryDirectory() as directory:
            with Database(directory) as db:
                collection = db.collection("events")

                def insert(index: int) -> str:
                    return collection.add({"index": index})["_id"]

                with ThreadPoolExecutor(max_workers=8) as pool:
                    identifiers = list(pool.map(insert, range(200)))
                self.assertEqual(len(set(identifiers)), 200)
                self.assertEqual(collection.count(), 200)
                self.assertEqual(db.metrics()["writes"], 200)


if __name__ == "__main__":
    unittest.main()
