# EflortableJD Architecture

> **Simple on the surface. Powerful underneath.**

## Scope of this build

This repository is the first executable milestone of EflortableJD. It intentionally delivers a correct, inspectable single-node engine before distributed consensus and cluster orchestration. The implementation is designed with explicit interfaces so replication, partition routing, and alternate storage engines can be added without rewriting the public document API.

| Area | v0.1 implementation | Extension point |
|---|---|---|
| Document model | JSON-compatible nested documents with generated or caller-supplied string IDs | Typed schemas, binary values, vectors |
| Durability | Versioned JSON snapshot plus checksummed append-only WAL | Segments, compaction, remote snapshots |
| Recovery | Snapshot load followed by WAL replay; torn final record is ignored and reported | Full corruption quarantine and repair |
| Queries | Equality/range operators, nested paths, projection, sorting, limit, cursor, count, distinct | Cost-based planner, aggregation, distributed execution |
| Indexes | Hash indexes for equality and optional uniqueness | B-tree, full-text, geospatial, vector |
| Concurrency | Thread-safe engine with collection-level locks and atomic single-document mutations | MVCC, lock sharding, actor scheduling |
| Network | Threaded HTTP/JSON API with bearer-token hook and request limits | Versioned binary protocol, multiplexing, streaming |
| Operations | CLI for start, status, shell, backup, restore, inspect, metrics, explain | Cluster membership and rolling upgrades |
| Security | Optional bearer token, collection allow-list hook, audit-ready request metrics | RBAC, TLS termination, tenant isolation |
| Distribution | Local routing interface and node metadata placeholders | Sharding, Raft/Multi-Raft, failover, rebalancing |

## Component boundaries

```text
Client / CLI
    |
    v
HTTP transport -> Request validation -> Query planner -> Collection API
                                      |              |
                                      v              v
                                  Index manager   Document store
                                                     |
                                                     v
                                             WAL + snapshot
```

The **document store** owns in-memory state and mutation semantics. The **WAL** is the source of durable mutation events. Snapshots are immutable point-in-time materializations, written atomically through a temporary file and rename. The **query layer** contains pure matching, projection, sorting, pagination, and explain logic. The **index layer** is deliberately small and explicit: indexes are only used when declared, avoiding invisible write amplification.

## Data and consistency model

Each collection is a map from document ID to the latest document version. A mutation is assigned a monotonically increasing database sequence number while holding the engine lock. A successful mutation is appended to the WAL, flushed, and then applied to the in-memory state; this ordering means an acknowledged write is recoverable after process failure. Reads are consistent with the latest applied sequence in the local process. The first milestone does not claim cross-node consistency.

Conditional updates use an `expected_version` precondition. This provides compare-and-swap semantics for callers that need optimistic concurrency without introducing distributed transactions. The HTTP layer returns a conflict response when the precondition fails.

## Storage strategy

The WAL uses newline-delimited JSON records with a format version, sequence number, operation, payload, and CRC32 checksum over the canonical record body. The snapshot stores the same format version, the last included sequence number, and all collection documents. On startup, the snapshot is validated before use and records after its sequence are replayed. A malformed or checksum-invalid final WAL record is treated as a likely torn write and is not applied; malformed records in the middle of the log fail startup rather than silently losing data.

This is not yet an LSM-tree. The interface is intentionally compatible with a future segmented storage implementation, while v0.1 keeps the code small enough to audit and test.

## Query model

The Python API accepts a dictionary filter:

```python
users.find({"age": {"$gte": 18}, "country": "Nepal"})
```

The HTTP API uses the same JSON shape. Supported operators are `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`, `$exists`, `$contains`, `$and`, `$or`, and `$not`. Field paths use dotted notation, such as `preferences.theme`. Queries are normalized into a small plan object, and `explain` reports whether a declared hash index was selected or a collection scan was used.

## Failure model

The engine protects against partial snapshot replacement, validates snapshot checksums, validates WAL checksums, and uses a deterministic replay sequence. The API exposes health and metrics for operators. Node failure, network partition, leader election, and rebalancing are reserved for a later milestone; v0.1 does not pretend to provide those guarantees.

## Roadmap

1. **Local durable database:** document API, checksummed WAL, snapshots, recovery, indexes, query execution, HTTP server, CLI, and tests.
2. **Storage evolution:** immutable segments, compaction, point-in-time snapshots, and corruption repair tooling.
3. **Concurrency:** MVCC read views, lock sharding, batch atomicity, and fault-injection tests.
4. **Cluster core:** node identity, membership, partition routing, replication log, and a measured consensus design.
5. **Production security:** TLS integration, RBAC, tenant boundaries, rate limiting, and audit export.
6. **Advanced access:** official SDKs, binary protocol, aggregation, full-text/vector extension interfaces, and benchmarks.

## Attribution

Ottahen  \
GitHub.com/Ottahen
