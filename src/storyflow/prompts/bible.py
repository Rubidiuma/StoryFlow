"""Version-one prompt for structured story-Bible generation."""

BIBLE_PROMPT_ID = "story_bible_v1"

BIBLE_PROMPT_V1 = """[story_bible_v1]
Create the initial story Bible from the supplied normalized story configuration.
Return only one JSON object with exactly these sections:
- world_rules, tone_rules, protagonist_core: non-empty strings
- required_elements, forbidden_elements: arrays of strings
- characters: a non-empty array of character objects with non-empty name and role;
  optional fields are location, motivation, known_facts, secrets, relationships, alive, version
- first_arc: an object with non-empty goal and conflict; optional fields are stage,
  exit_conditions, status, summary
Do not include prose outside the object.
"""

__all__ = ["BIBLE_PROMPT_ID", "BIBLE_PROMPT_V1"]
