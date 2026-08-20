import random
import tempfile
import unittest

from efortablejd import Database
from efortablejd.networking.protocol import MAX_FRAME, ProtocolError, decode_frame, encode_frame


class PropertyTests(unittest.TestCase):
    def test_write_read_property_for_random_documents(self):
        randomizer = random.Random(1729)
        with tempfile.TemporaryDirectory() as directory:
            with Database(directory) as db:
                collection = db.collection("property")
                expected = {}
                for index in range(100):
                    document = {"n": index, "value": randomizer.choice([None, True, False, index, f"v-{index}"]), "nested": {"x": randomizer.randrange(0, 1000)}}
                    created = collection.add(document)
                    expected[created["_id"]] = created
                for identifier, document in expected.items():
                    self.assertEqual(collection.get(identifier), document)

    def test_invalid_protocol_inputs_fail_closed(self):
        class Stream:
            def __init__(self, data: bytes):
                self.data = data
            def recv(self, amount: int) -> bytes:
                data, self.data = self.data[:amount], self.data[amount:]
                return data
        for raw in (b"\x00\x00\x00\x00", b"\xff\xff\xff\xff", b"\x00\x00\x00\x03bad"):
            with self.assertRaises((ProtocolError, EOFError)):
                decode_frame(Stream(raw))
        with self.assertRaises(ProtocolError):
            encode_frame({"body": "x" * (MAX_FRAME + 1)})


if __name__ == "__main__":
    unittest.main()
