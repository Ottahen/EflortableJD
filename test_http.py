import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection

from efortablejd.networking.http import EflortableJDServer
from efortablejd.storage.engine import Database


class HTTPTests(unittest.TestCase):
    def test_http_crud_and_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(directory)
            server = EflortableJDServer(("127.0.0.1", 0), database, auth_token="secret")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            host, port = server.server_address
            try:
                connection = HTTPConnection(host, port, timeout=3)
                connection.request("GET", "/health")
                response = connection.getresponse()
                self.assertEqual(response.status, 401)
                response.read()
                headers = {"Authorization": "Bearer secret", "Content-Type": "application/json"}
                connection.request("POST", "/v1/users", body=json.dumps({"name": "Alex", "age": 21}), headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                created = json.loads(response.read())
                self.assertEqual(created["data"]["name"], "Alex")
                connection.request("GET", "/v1/users?query=%7B%22age%22%3A%7B%22%24gte%22%3A18%7D%7D", headers={"Authorization": "Bearer secret"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["count"], 1)
            finally:
                server.shutdown()
                server.server_close()
                database.close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
