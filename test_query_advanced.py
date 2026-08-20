import tempfile
import unittest

from efortablejd import Database


class AdvancedQueryTests(unittest.TestCase):
    def test_operators_and_aggregation_pipeline(self):
        with tempfile.TemporaryDirectory() as directory:
            with Database(directory) as db:
                orders = db.collection("orders")
                orders.add_many([
                    {"customer": "a", "status": "paid", "amount": 10, "tags": ["new", "priority"]},
                    {"customer": "a", "status": "paid", "amount": 20, "tags": ["priority"]},
                    {"customer": "b", "status": "open", "amount": 5, "tags": ["new"]},
                ])
                self.assertEqual(orders.count({"tags": {"$all": ["new", "priority"]}}), 1)
                self.assertEqual(orders.count({"customer": {"$regex": "^[ab]$"}}), 3)
                self.assertEqual(orders.count({"tags": {"$size": 1}}), 2)
                grouped = orders.aggregate([
                    {"$match": {"status": "paid"}},
                    {"$group": {"_id": "$customer", "total": {"$sum": "$amount"}, "average": {"$avg": "$amount"}, "count": {"$sum": 1}}},
                    {"$sort": {"_id": 1}},
                ])
                self.assertEqual(grouped, [{"_id": "a", "total": 30, "average": 15.0, "count": 2}])

    def test_lookup_and_unwind(self):
        with tempfile.TemporaryDirectory() as directory:
            with Database(directory) as db:
                users = db.collection("users")
                users.add({"user_id": "u1", "name": "Alex"})
                events = db.collection("events")
                events.add({"user_id": "u1", "kinds": ["login", "read"]})
                result = events.aggregate([
                    {"$unwind": "$kinds"},
                    {"$lookup": {"from": "users", "localField": "user_id", "foreignField": "user_id", "as": "user"}},
                    {"$project": {"kinds": 1, "user": 1}},
                ])
                self.assertEqual(len(result), 2)
                self.assertEqual(result[0]["user"][0]["name"], "Alex")


if __name__ == "__main__":
    unittest.main()
