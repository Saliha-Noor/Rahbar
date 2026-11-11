# ADR 0003: Semantic cache in Redis, invalidated by index_id

## Status
Accepted

## Context
Generation is the slow step, and repeated or paraphrased questions can otherwise pay for another model call. A cache must not serve an answer from a previous corpus index after re-indexing. It must be shared by all API replicas and survive an API pod restart.

## Decision
Use Redis with a PVC. The current ConfigMap sets `CACHE_THRESHOLD=0.92` and `CACHE_TTL=86400`. The API stores the question vector and response under a key scoped by the current Chroma `index_id` (`api/app/services/cache.py`). The indexer writes a new `index_id` into Chroma metadata; the API's cache lookup uses the current index ID, so old entries stop matching after re-index and expire by TTL. NetworkPolicy allows the API to reach Redis; the indexer does not need Redis access.

Only grounded answers that pass citation validation are cached (`api/app/services/answer.py:127-129`). Abstentions and generation fallbacks are not cached. The request schema has no conversation-history field; if that feature is added, follow-up requests must bypass the cache.

## Threshold measurement status

The checked-in threshold is 0.92. `eval/cache_probe.py` is present, but the uploaded repository does not contain its output or a record of tested thresholds, false hits, or missed paraphrases. Therefore the team cannot yet claim that 0.92 is the lowest threshold with zero false hits. Run the probe, save the output, and update this ADR with the tested values and the actual false-hit pair (if any).

## Options considered
- **Second Chroma collection:** rejected because it introduces another writer to the Chroma component and couples cache writes to the vector store.
- **Indexer flushes Redis:** rejected because the NetworkPolicy deliberately allows Redis access only from the API.
- **No cache:** simplest and correct, but repeated questions incur another generation call.

## Consequences
- Cache entries are shared across API replicas and scoped to a corpus index.
- The cache is best-effort; cache failures are treated as misses.
- Threshold selection still requires measured false-hit and missed-paraphrase evidence.
