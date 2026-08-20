# EflortableJD Production Invariants

This document is the engineering contract for the expansion from a local foundation into a real database system. A feature is not considered complete until its invariant is enforced by code and covered by a test.

| Invariant | Enforcement target | Failure behavior |
|---|---|---|
| An acknowledged mutation is recoverable | WAL flush before state acknowledgement | Return an error; never acknowledge an unlogged write |
| WAL sequence numbers are strictly increasing | Recovery validator and writer lock | Refuse startup on middle-log corruption |
| Snapshots are atomic and self-validating | Temporary file, fsync, replace, SHA-256 | Keep the previous snapshot and fail recovery if the active one is invalid |
| A document ID is unique within a collection | Mutation precondition | Return a conflict without adding a WAL record |
| Unique indexes never contain duplicate keys | Preflight validation plus index rebuild validation | Reject the mutation or index creation |
| Conditional writes cannot overwrite a newer version | Version precondition under the mutation lock | Return a conflict |
| A read view is internally consistent | MVCC snapshot sequence | Read only versions visible at the requested sequence |
| A batch is all-or-nothing locally | Validate every operation before one WAL record | Roll back in-memory staging and append nothing on validation failure |
| Tenant data is isolated | Tenant-scoped collection routing and authorization | Reject cross-tenant access before query execution |
| Quorum writes are acknowledged only after quorum durability | Replica acknowledgements | Return unavailable when quorum cannot be reached |
| A failed primary cannot accept writes | Membership state and lease/term checks | Return not-leader/unavailable and route to the elected primary |
| Corrupt data is never silently returned | Checksums and typed corruption errors | Fail closed and expose the affected sequence/segment |
| Backups are verifiable | Manifest hashes and restore check | Reject invalid backup before replacing destination data |
| Metrics represent observed events | Counters/timers updated at operation boundaries | Never emit fabricated benchmark or health claims |

## Current foundation audit

The existing v0.1 repository already has a working local WAL, snapshot, document API, hash index, HTTP API, CLI, and tests. Its material limitations are intentional but must be addressed for a genuinely powerful build: collection-level state is currently latest-version-only, batches are not atomic, query execution is mostly collection-scan based, the network API is HTTP/JSON only, authorization is token-only, there is no cluster membership or replication, and backup is snapshot plus WAL copying without point-in-time verification.

The expansion will preserve the public Python API where possible while adding explicit versioned interfaces. It will not claim Raft, TLS, or cross-process replication until those behaviors are implemented and exercised.

## Definition of done for this expansion

The repository must install without hidden runtime dependencies, start a real server, reopen data after process termination, reject invalid or unauthorized operations, support deterministic in-process cluster tests, expose operational state, and fail tests when a documented guarantee is violated. Every distributed guarantee will be labeled with its actual scope: local process, same-host multi-node simulation, or cross-process networked behavior.

## Attribution

Ottahen  \
GitHub.com/Ottahen
