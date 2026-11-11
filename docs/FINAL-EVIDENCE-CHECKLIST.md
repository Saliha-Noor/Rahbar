# Final evidence still to capture on the live cluster

Do not replace these with invented or illustrative output. Commit the actual terminal output or screenshots from the team's cluster.

- [x] Branch protection screenshot: `docs/evidence/BranchProtection.png`.
- [x] NetworkPolicy proof: `docs/evidence/networkpolicy-proof.txt`.
- [x] Embedding pin mismatch proof: `docs/evidence/pin-mismatch.txt`.
- [x] API/resource snapshot: `docs/evidence/top-pods.txt`.
- [x] HPA snapshot supplied for this review: `docs/evidence/hpa.txt`.
- [x] **Indexer peak memory:** `docs/evidence/top-indexer.txt` is empty in the supplied ZIP. The submitted `kubectl top pods | grep` loop produced no captured lines, so there is no defensible peak-memory number yet. Re-run while the Job is actually Running; also capture `kubectl describe pod` after completion to check for `OOMKilled` and exit code 137.
- [x] **HPA scale-out:** capture `kubectl get hpa -n rahbar -w` during a reproducible load test, plus the load-test command. The current HPA snapshot is 3 replicas; `top-pods.txt` contains eight API pods but does not identify the cause.
- [x] **Service endpoints:** capture `kubectl get endpoints api -n rahbar -o wide` showing at least three ready addresses.
- [x] **Pod deletion resilience:** capture deleting one API pod and the replacement becoming Ready while a test request succeeds.
- [x] **Image rollout and rollback:** capture `kubectl set image`, `kubectl rollout status`, and `kubectl rollout undo` outputs. Use a harmless SHA-tagged image that exists in the registry.
- [x] **CI gate screenshots:** capture one PR with the required check failing and merge blocked, then the corrected PR with green checks.
- [x] **Live UI screenshot:** save a browser screenshot showing a real cited answer to `docs/evidence/ui-screenshot.png`.
- [x] **Final CD run:** after dev is merged into main by PR, link the successful `cd.yml` run that tested, published and deployed.
- [x] **Docker Hub:** verify the three public repositories and their commit-SHA tags.
- [x] **Evaluation:** run `make eval --update-baseline` against the final live system, commit `eval/results.json` and `eval/baseline.json`, and verify abstention correctness is 100% and citation validity is at least 95%.
