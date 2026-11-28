Generate Batch B: 13 documents with planted problems (assignment, Part A).

    python scripts/make_batch_b.py                      # writes corpus/batch_b/
    python scripts/make_batch_b.py --out /tmp/batch_b --supersede fee-structure-page.html

The documents are SYNTHETIC (a made-up student-services circular series), written for RAGOps
testing. They say so in their text. Nothing here is real FAST-NUCES policy.

Planted problems (also listed in corpus/batch_b/README.md):
  exact duplicate x2 ........ library-borrowing-policy-copy.md, scholarship-policy-mirror.md
  near-duplicate ............ student-id-card-policy-reissue.md
  truncated ................. it-services-policy-truncated.md
  corrupt ................... corrupt-circular.pdf
  missing metadata .......... campus-sports-notice.md
  newer version ............. fee-structure-update-2027.md (supersedes the existing fee page)
  injected instruction ...... exam-conduct-circular.md
  clean (4) ................. library, scholarship, id-card, it-services, career-services
