import tempfile
import unittest

from efortablejd.cluster import Cluster, ClusterUnavailable, Consistency


class ClusterTests(unittest.TestCase):
    def test_replicated_quorum_write_and_read(self):
        with tempfile.TemporaryDirectory() as directory:
            with Cluster(directory, ["n1", "n2", "n3"], replication_factor=3) as cluster:
                write = cluster.write("users", "insert", {"document": {"_id": "u1", "name": "Alex"}}, consistency=Consistency.QUORUM)
                self.assertEqual(write["acknowledgements"], 3)
                result = cluster.read("users", {"_id": "u1"}, consistency=Consistency.STRONG)
                self.assertEqual(result[0]["name"], "Alex")
                self.assertEqual(cluster.status()["nodes"]["n2"]["applied_index"], 1)

    def test_quorum_fails_when_too_many_nodes_are_down(self):
        with tempfile.TemporaryDirectory() as directory:
            with Cluster(directory, ["n1", "n2", "n3"], replication_factor=3) as cluster:
                cluster.kill("n2")
                cluster.kill("n3")
                with self.assertRaises(ClusterUnavailable):
                    cluster.write("users", "insert", {"document": {"_id": "u1"}}, consistency=Consistency.QUORUM)


if __name__ == "__main__":
    unittest.main()
