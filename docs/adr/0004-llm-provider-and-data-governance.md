# ADR 0004: LLM provider and data governance

## Status
Accepted · 2026-11-07

## Context
On every request the model receives the user's question and the retrieved passages. The corpus
is public (FAST-NUCES documents downloaded from the university website). The question is
free text typed by a student and could contain personal details. The provider is chosen by
`LLM_PROVIDER` in the ConfigMap, behind one interface (`api/app/providers/llm/base.py`).

## Decision
- **Default and fully supported mode: `ollama-host`.** Ollama runs on the developer's laptop and
  the cluster reaches it at `host.minikube.internal:11434`. Models: `llama3.2:3b` for generation and
  `nomic-embed-text` for embeddings. The question and the retrieved text never leave the laptop.
- **`hosted`** is implemented (OpenAI-compatible endpoint, `api/app/providers/llm/hosted.py`) but
  not our default; STARTER-TODO: say whether you tested it against a live endpoint, and which one.
  It sends the question and retrieved text to a third party. The key comes from a Kubernetes Secret
  (`LLM_API_KEY`), is never written in a committed manifest, and error handling records only the
  exception type, so a key or header cannot end up in a log line.
- **`ollama-incluster`** (bonus) is not deployed by us. The same `OllamaProvider` works if
  `OLLAMA_URL` points at an in-cluster Service.
- **Temperature 0.2**, set in the ConfigMap: facts and JSON need low variance. It does not
  cure hallucination, which is why abstention and the citation check exist.
- **The embedding model is pinned separately** from the generation model, in the same ConfigMap
  for the indexer and the API, and enforced in code (see PIPELINE.md, Embedding): vectors from
  two models are not comparable and the failure is silent.

## Options considered
- **Hosted free tier (Groq, Google AI Studio, OpenRouter):** fast and no laptop dependency, but the
  data leaves our machine and the free tier has rate limits that would make CI and demos flaky.
- **In-cluster Ollama:** keeps everything inside the cluster, but needs 8 GB or more for minikube
  and a long startup probe because the weights take minutes to load.

## Consequences
- What stays on the laptop: questions, retrieved passages, generated answers, embeddings.
- What we log: request id, route, status, latency; and per answer the `top_k`, chunk ids,
  similarity scores and whether it abstained. We do not log the question text or the prompt.
- What would leave it with `hosted`: the question and the retrieved text.
- Before using private documents (for example student records) we would keep to local or
  in-cluster models, add authentication in front of the API, and review what the logs capture.
- A trade-off: the demo needs Ollama on the machine that runs the cluster.
