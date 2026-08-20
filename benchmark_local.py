"""Measure the local engine on the current machine.

This script reports measurements from the current run only; it contains no claimed
baseline or synthetic performance numbers.
"""

from __future__ import annotations

import argparse
import statistics
import tempfile
import time

from efortablejd import Database


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * fraction)))
    return ordered[index]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=int, default=1000)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory() as directory, Database(directory) as db:
        collection = db.collection("bench")
        collection.create_index("email", unique=True)
        write_latencies: list[float] = []
        for index in range(args.documents):
            started = time.perf_counter()
            collection.add({"email": f"user-{index}@example.com", "age": index % 100, "payload": "x" * 32})
            write_latencies.append((time.perf_counter() - started) * 1000)
        read_latencies: list[float] = []
        for index in range(args.documents):
            started = time.perf_counter()
            collection.find({"email": f"user-{index}@example.com"})
            read_latencies.append((time.perf_counter() - started) * 1000)
        print("EflortableJD local benchmark; results are machine-specific observations")
        for name, values in (("write_ms", write_latencies), ("indexed_read_ms", read_latencies)):
            print(f"{name}: count={len(values)} mean={statistics.mean(values):.3f} p50={percentile(values, 0.50):.3f} p95={percentile(values, 0.95):.3f} p99={percentile(values, 0.99):.3f}")
        print(f"metrics: {db.metrics()}")


if __name__ == "__main__":
    main()
