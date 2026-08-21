"""Version-one prompt for deterministic structured scene planning."""

DIRECTOR_PROMPT_ID = "scene_director_v1"

DIRECTOR_PROMPT_V1 = """[scene_director_v1]
All natural-language output fields, especially goal, conflict, beats, reason and option text, MUST use Simplified Chinese.
Plan exactly one complete story scene from the supplied context.

CONTINUITY, CAUSALITY, AND NON-REPETITION (read the context carefully first):
- rolling_summary, older_scene_summaries and recent_scenes describe what has ALREADY happened.
  Do NOT re-plan or restate events, revelations, or beats that already occurred. Advance the story.
- This scene must follow causally from the most recent scene and from the reader's last choice
  (see the choices layer): honor the consequences of that choice rather than resetting them.
- active_threads are open plot lines that need progress; foreshadowing lists planted clues that
  should eventually pay off. Prefer beats that push an active thread forward or develop a clue.
- characters carry known_facts, relationships, location and alive status: stay consistent with
  them. A character cannot re-learn what they already know or reappear if not alive.
- Each scene should change the situation (new information, a decision, a shift in location or
  relationship) so consecutive scenes never feel like variations of the same moment.

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
- reason: string — why the protagonist must choose right now (WRITE IN CHINESE)
- options: exactly 3 objects, each with:
  - position: 0, 1, or 2
  - text: a SHORT concrete action the PROTAGONIST takes, written in first-person-adjacent
    imperative, IN CHINESE (e.g. "进入酒馆询问掌柜", "翻越围墙逃脱", "直接质问对方身份")
    NOT meta-narrative analysis. NOT "接受现实选择功法". NOT character trait descriptions.
  - effects: {"route_change": "brief description in Chinese of where this choice leads"}

The three option texts must describe what the PROTAGONIST DOES — observable actions,
not internal states, narrative directions, or world-building commentary.

Do not write story prose. Return only the JSON object.
"""

__all__ = ["DIRECTOR_PROMPT_ID", "DIRECTOR_PROMPT_V1"]
