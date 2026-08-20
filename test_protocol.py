import tempfile
import threading
import unittest

from efortablejd.networking.protocol import DatabaseClient, EflortableJDProtocolServer
from efortablejd.storage.engine import Database


class ProtocolTests(unittest.TestCase):
    def test_framed_client_server_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory)
            server = EflortableJDProtocolServer(("127.0.0.1", 0), database)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            try:
                with DatabaseClient(host, port) as client:
                    self.assertEqual(client.ping()["protocol"], 1)
                    created = client.insert("users", {"name": "Alex"})
                    self.assertEqual(client.find("users", {"_id": created["_id"]})[0]["name"], "Alex")
                    self.assertEqual(client.find("users", {"name": "Alex"})[0]["_id"], created["_id"])
            finally:
                server.shutdown()
                server.server_close()
                database.close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
