"""Sub-agent orchestration: define, persist, and run small multi-agent teams.

- ``teams``: the CRUD layer — team definitions saved as JSON files plus built-in presets.
- ``toolbelt``: the curated subset of local-mcp tools that team agents may call.
- ``runner``: the engine that runs a team sequentially against the configured LLM backend.
"""
