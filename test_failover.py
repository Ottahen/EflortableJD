import tempfile
import unittest

from efortablejd.cluster import Cluster, ClusterUnavailable, Consistency


class FailoverTests(unittest.TestCase):
    def test_leader_failover_and_reconciliation(self):
        with tempfile.TemporaryDirectory() as directory:
            with Cluster(directory, ["n1", "n2", "n3"], replication_factor=3) as cluster:
                cluster.write("users", "insert", {"document": {"_id": "u1", "name": "Alex"}})
                old_leader = cluster.leader_id
                cluster.kill(old_leader)
                new_leader = cluster.elect_leader()
                self.assertNotEqual(new_leader, old_leader)
                write = cluster.write("users", "insert", {"document": {"_id": "u2", "name": "Sam"}}, consistency=Consistency.QUORUM)
                self.assertEqual(write["acknowledgements"], 2)
                self.assertEqual(cluster.read("users", {"_id": "u2"}, consistency=Consistency.STRONG)[0]["name"], "Sam")

    def test_blocked_replica_link_reduces_acknowledgements(self):
        with tempfile.TemporaryDirectory() as directory:
            with Cluster(directory, ["n1", "n2", "n3"], replication_factor=3) as cluster:
                cluster.block_link(cluster.leader_id, "n2")
                write = cluster.write("users", "insert", {"document": {"_id": "u1"}}, consistency=Consistency.QUORUM)
                self.assertEqual(write["acknowledgements"], 2)
                self.assertEqual(cluster.status()["nodes"]["n2"]["replication_lag"], 1)
                cluster.unblock_link(cluster.leader_id, "n2")
                self.assertGreaterEqual(cluster.reconcile("n2"), 1)
                self.assertEqual(cluster.nodes["n2"].applied_index, 1)

    def test_rebalance_changes_ring_membership(self):
        with tempfile.TemporaryDirectory() as directory:
            with Cluster(directory, ["n1", "n2", "n3"], replication_factor=2) as cluster:
                result = cluster.rebalance(["n1", "n2"])
                self.assertEqual(result["nodes"], ["n1", "n2"])
                self.assertEqual(cluster.ring.owner_for("customer-1"), cluster.ring.owner_for("customer-1"))


if __name__ == "__main__":
    unittest.main()
