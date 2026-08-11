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

ROLLING_SUMMARY_PROMPT_V1 = """[rolling_summary_v1]
You are given several recent story scenes and the current rolling summary.
Compress them into a single rolling_summary string that preserves the most
important events, character changes, and unresolved threads.
Return only one JSON object with exactly one key:
  {"rolling_summary": "<compressed summary>"}
Do not include prose outside the JSON object.
"""

NEXT_ARC_PROMPT_V1 = """[next_arc_v1]
You are given the current story bible, the completed arc summary, the current memory snapshot,
and the active narrative threads. Generate the next story arc.
Return only one JSON object with these keys:
  goal          – the arc's primary narrative goal (string)
  conflict      – the central conflict driving this arc (string)
  stage         – one of: exposition, rising, climax, falling, resolution
  exit_conditions – an array of strings describing when this arc ends
  summary       – an empty string (arc has not started yet)
The new arc must not contradict world_rules or any confirmed past events.
Do not include prose outside the JSON object.
"""

__all__ = [
    "MEMORY_UPDATE_PROMPT_V1",
    "ROLLING_SUMMARY_PROMPT_V1",
    "NEXT_ARC_PROMPT_V1",
]
