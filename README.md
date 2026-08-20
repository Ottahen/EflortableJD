# EflortableJD

> **Simple on the surface. Powerful underneath.**

EflortableJD is a modular document database prototype built from first principles around a clean developer API. The current build is a runnable engine with durable storage, a checksummed WAL, atomic snapshots, version history, atomic batches, hash and composite indexes, aggregation, a versioned framed protocol, an HTTP API, tenant-aware RBAC, rate limiting, audit logs, verified backups, point-in-time restore, deterministic multi-node replication, failover simulation, operational metrics, a CLI, benchmarks, and tests.

## Quick start

The project uses only the Python standard library at runtime.

```bash
cd EflortableJD
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
efdb start --path ./data
```

In another terminal, create and query a document:

```bash
curl -X POST http://127.0.0.1:7700/v1/users \
  -H 'Content-Type: application/json' \
  -d '{"name":"Alex","email":"alex@example.com","age":21}'

curl 'http://127.0.0.1:7700/v1/users?query={"age":{"$gte":18}}'
```

## Python API

```python
from efortablejd import Database

with Database("./data") as db:
    users = db.collection("users")
    users.create_index("email", unique=True)
    users.add({"name": "Alex", "email": "alex@example.com", "age": 21})
    adults = users.find({"age": {"$gte": 18}}, sort=[("age", "desc")], limit=20)
    users.update({"email": "alex@example.com"}, {"$set": {"name": "Alex Smith"}})
```

The supported query operators are `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in`, `$nin`, `$exists`, `$contains`, `$and`, `$or`, and `$not`. Nested document paths use dotted names such as `preferences.theme`.

## Security and multi-node operation

Set `EFDB_CREDENTIALS=/path/credentials.json` before `efdb start` to activate PBKDF2-backed bearer tokens, tenant-scoped collections, RBAC, rate limiting, and an audit hash chain. Create a user with `efdb user-create --credentials /path/credentials.json --username alex --tenant team-a --roles writer`. The same-process cluster API is available from `efortablejd.cluster` with explicit quorum, failure injection, reconciliation, and leader-election methods. Its scope is documented honestly in [`docs/IMPLEMENTATION_STATUS.md`](docs/IMPLEMENTATION_STATUS.md).

## CLI

| Command | Purpose |
|---|---|
| `efdb start` | Start the HTTP server. |
| `efdb status` | Show collections, sequence, and index metadata. |
| `efdb metrics` | Show local operational counters. |
| `efdb inspect --collection users` | Show collection count, indexes, and a sample. |
| `efdb explain users '{"email":"alex@example.com"}'` | Show scan versus index strategy. |
| `efdb compact` | Write a durable snapshot and truncate obsolete WAL records. |
| `efdb backup ./backup` | Write a verified snapshot, WAL copy, and manifest. |
| `efdb verify-backup ./backup` | Verify backup manifest and file checksums. |
| `efdb pitr ./backup ./restored 12` | Materialize a verified point-in-time restore at sequence 12. |
| `efdb user-create --credentials ./credentials.json --username alex --roles writer` | Create a tenant-scoped hashed-credential user. |
| `efdb restore ./backup --path ./restored` | Restore a backup into a database directory. |
| `efdb shell` | Read JSON commands from standard input. |

## HTTP API

The API exposes `GET /health`, `GET /v1/status`, `GET /v1/metrics`, `GET /v1/inspect`, `POST /v1/checkpoint`, and collection routes. `POST /v1/{collection}` inserts a document, `GET /v1/{collection}` queries documents, `PATCH /v1/{collection}` updates by filter, and `DELETE /v1/{collection}` deletes by filter. A bearer token can be required by setting `EFDB_AUTH_TOKEN` or passing `--auth-token`.

## Reliability model

An acknowledged mutation is written to the WAL and flushed before it is applied in memory. Snapshot replacement is atomic, and both snapshots and WAL records are checksummed. Reopening a database loads the snapshot and deterministically replays later WAL records. A truncated final WAL line is treated as a torn write; invalid records in the middle of the log fail recovery rather than being silently ignored.

## What remains outside the completed production claim

The same-process replication and failover model is real and tested, but it is not a completed cross-process Raft implementation. Native TLS certificate management, rolling upgrades, background LSM compaction, page-cache optimization, and cross-process chaos testing remain separate production milestones. The repository reports these boundaries explicitly and never presents simulated behavior as a completed distributed deployment.

## Attribution

Ottahen  \
GitHub.com/Ottahen
