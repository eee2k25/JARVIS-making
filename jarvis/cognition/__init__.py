"""Cognitive Processing Pipeline — LLM decision core.

Talks to any OpenAI-compatible REST endpoint (OpenAI, Groq, OpenRouter,
Together, Ollama, LM Studio, ...) and compiles heuristic output into a
strict, executor-safe Action plan. Falls back to a deterministic
OfflineBrain when no endpoint/key is configured, so the perceive -> reason
-> act loop is always demonstrable.
"""
