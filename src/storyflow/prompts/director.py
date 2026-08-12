"""Version-one prompt for deterministic structured scene planning."""

DIRECTOR_PROMPT_ID = "scene_director_v1"

DIRECTOR_PROMPT_V1 = """[scene_director_v1]
Plan exactly one complete story scene from the supplied context.
Return only one JSON object with these fields:

- goal: string — what the scene achieves narratively
- conflict: string — the tension or obstacle in this scene
- beats: array of strings — ordered scene beats (3-5 items)
- choice_suggestion: null, OR a choice object when the scene ends at a decision point

CRITICAL: Use EXACT character names from the character list provided in context.
NEVER translate names to English, pinyin, or other representations.
Only use the exact names as they appear in the characters array.

If you include a choice_suggestion, it must be a protagonist-action choice:
- type: "decision", "action", or "dialogue" (never use "character_direction" or other types)
- reason: string — why the protagonist must choose right now
- options: exactly 3 objects, each with:
  - position: 0, 1, or 2
  - text: a SHORT concrete action the PROTAGONIST takes, written in first-person-adjacent
    imperative (e.g. "进入酒馆询问掌柜", "翻越围墙逃脱", "直接质问对方身份")
    NOT meta-narrative analysis. NOT "接受现实选择功法". NOT character trait descriptions.
  - effects: {"route_change": "<brief description of where this choice leads>"}

The three option texts must describe what the PROTAGONIST DOES — observable actions,
not internal states, narrative directions, or world-building commentary.

Do not write story prose. Return only the JSON object.
"""

__all__ = ["DIRECTOR_PROMPT_ID", "DIRECTOR_PROMPT_V1"]
