"""Version-one prompt for deterministic structured scene planning."""

DIRECTOR_PROMPT_ID = "scene_director_v1"

DIRECTOR_PROMPT_V1 = """[scene_director_v1]
Plan exactly one complete story scene from the supplied context.
Return only one JSON object compatible with ScenePlan:
- goal and conflict: non-empty strings
- beats: a non-empty ordered array of non-empty strings
- choice_suggestion: null or one choice object with type, reason, and exactly three
  distinct options; every option contains non-empty text, non-empty structured effects,
  and its zero-based position
Do not write scene prose and do not include text outside the JSON object.
"""

__all__ = ["DIRECTOR_PROMPT_ID", "DIRECTOR_PROMPT_V1"]
