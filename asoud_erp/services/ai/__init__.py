"""The LLM-facing layer for the in-product assistant (Gemloy / Gemma 4 26B).

No API endpoint yet: the orchestrator is driven by pure tests with a fake
transport and a fake executor. See ``docs/api/ai_assistant.md`` for the design,
the model limits and the privacy rules.
"""
