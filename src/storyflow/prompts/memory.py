"""Version-one prompt text for structured memory updates."""

MEMORY_UPDATE_PROMPT_V1 = """[memory_update_v1]
Derive a memory update from the supplied committed scene and current memory snapshot.
Return only one JSON object and omit fields that have not changed. Allowed fields are:
- characters: an array of complete character-state objects
- active_threads: an array of strings replacing the current active threads
- foreshadowing: an array of objects with exactly id, description, and status; status must be
  planted, active, resolved, or abandoned
- rolling_summary: a string replacing the current rolling summary
Do not include prose outside the JSON object.
"""

__all__ = ["MEMORY_UPDATE_PROMPT_V1"]
