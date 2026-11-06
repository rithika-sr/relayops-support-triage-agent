# 0002: Postgres for domain state, jobs, checkpoints, events, and vectors

Status: accepted

## Context

The runtime needs durable jobs, resumable graph state, ordered events, an action ledger, and vector search. Extra
infrastructure (Redis, Celery, a vector database) adds failure modes for a local product.

## Decision

Use one Postgres 17 instance with pgvector. Jobs are rows claimed with `FOR UPDATE SKIP LOCKED` and leases; graph
state uses LangGraph's `PostgresSaver`; events use a per-run sequence; knowledge uses tsvector plus a 768-d vector
column with exact cosine search.

## Consequences

- One backup and migration story; transactional outbox and ledger semantics come for free.
- Exact vector search is fine for the synthetic corpus; an approximate index needs benchmarking before adoption.
- A single worker processes jobs sequentially; scaling out is safe (advisory locks) but limited by one local model.
