# ADR 0004: Pluggable LLM provider and local-first data handling

## Status
Accepted

## Context
The model receives a student's question and the retrieved document passages. Questions may contain personal details even though the indexed FAST-NUCES corpus is public. Provider choice therefore affects whether request content leaves the developer's machine.

## Decision
- **Default mode: `ollama-host`.** Ollama runs on the host and the cluster reaches it at `host.minikube.internal:11434`. The checked-in ConfigMap sets `LLM_MODEL=llama3.2:1b` and `EMBED_MODEL=nomic-embed-text`. The model name must match the ConfigMap when pulled locally.
- **Hosted mode:** implemented through the OpenAI-compatible provider in `api/app/providers/llm/hosted.py`, but no live hosted-provider test is evidenced in the uploaded repository. It must therefore be treated as implemented but not demonstrated. When enabled, the question and retrieved passages are sent to the configured third party. The API key is injected through the Kubernetes Secret, not committed in Git.
- **In-cluster Ollama:** not deployed by this project. The provider interface can point to an in-cluster Ollama service, but the required deployment and storage are not present in the base manifests.
- **Temperature:** 0.2 in the ConfigMap. Low variance is appropriate for factual answers and structured JSON, but it does not prevent hallucinations; relevance-floor abstention and citation validation remain necessary.
- **Embedding pin:** generation and embedding model names are separate. The same `EMBED_MODEL` is consumed by API and indexer and checked against Chroma metadata.

## Options considered
- **Hosted free tier:** avoids a local model dependency but sends the question and retrieved content outside the machine and may introduce rate limits. Not selected as the default.
- **In-cluster Ollama:** keeps inference within Kubernetes but increases minikube memory requirements and requires a long startup probe for model loading.

## Consequences and data handling
- In default mode, questions, retrieved passages, embeddings, and generated answers are processed through the host Ollama endpoint.
- The application logs request IDs, route/status, latency, retrieval identifiers/scores, and outcome metrics; it should not log question text, prompts, or API keys.
- Before indexing private student records, add authentication/authorization, review retention and logging, and keep inference local or in an approved environment.
- The demo depends on Ollama running on the host that owns the cluster.
