# ADR 0003: Semantic cache in Redis, invalidated by index_id

## Status
Accepted · 2026-11-07

## Context
Generation is the slow and costly step, and students ask near-identical questions
("what CGPA means academic warning?"). A cache saves a model call. It also has a sharp edge:
a cached mistake is served to everyone, and after a re-index the old answers outlive the
index they came from.

Constraints from the architecture: the API is the only reader of the vector store and the
indexer is the only writer; Redis is reachable from the API only (NetworkPolicy), so the
indexer cannot flush it; the cache must survive a pod restart and be shared by 3 replicas.

## Decision
Redis with a PVC. A hit is cosine similarity at or above `CACHE_THRESHOLD`, read from the
ConfigMap. Each entry stores the question vector and the full response under the key
`cache:<index_id>:<uuid>` with a TTL (`CACHE_TTL`). The code is `api/app/services/cache.py`.

Threshold: STARTER-TODO: shipped value, chosen with `eval/cache_probe.py` as the lowest value with zero
false hits on our test pairs. We tried STARTER-TODO: the 2 or 3 values; STARTER-TODO: value was ruled out by the
false hit "STARTER-TODO: question A" vs "STARTER-TODO: question B" (similarity STARTER-TODO).

Never cached (`api/app/services/answer.py`): abstentions and out-of-scope answers, fallbacks
and anything that failed validation, and follow-up questions. The request schema has no
conversation history, so every request is standalone and no follow-up can reach the cache.
If a history field is added later, the cache must be skipped when it is present.

**Invalidation on re-index.** The indexer writes a new `index_id` into the Chroma collection
metadata (`indexer/pipeline/store.py:32`). The API reads it (refreshed every 30 s) and puts it in every cache key and
lookup prefix. After a re-index, entries from the old index are never matched, and the TTL
removes them. The indexer never needs to reach Redis.

## Options considered
- **A second Chroma collection:** rejected. The API would become a writer to Chroma, which breaks
  the rule of one writer and one reader, and would let a bad cache write corrupt the vector store's
  volume. It also adds load to the component that must stay simple.
- **Indexer flushes Redis after indexing:** rejected. The NetworkPolicy lets only the API reach
  Redis, and opening it for the indexer widens the attack surface for a small gain.
- **No cache:** simplest, and correct, but every repeated question pays a full model call.

## Consequences
- Easier: repeat questions are fast; a re-index invalidates the cache with no extra step.
- Harder: lookup scans the entries under the current `index_id` and computes cosine in Python,
  which is fine at classroom scale (hundreds of entries) but would need a vector index (Redis
  Stack or similar) at thousands.
- Watch for: a threshold that is too low serves a wrong answer to a different question;
  a Redis outage is handled by treating it as a miss (the cache is best-effort), and `/readyz`
  still reports Redis as a dependency.
