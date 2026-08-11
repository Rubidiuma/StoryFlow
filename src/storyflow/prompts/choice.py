"""Versioned prompt for normalizing a reader-authored custom action."""

CUSTOM_ACTION_EFFECTS_PROMPT_V1 = """[custom_action_effects_v1]
Convert the reader's custom action into one JSON object containing at least one normalized effect.
Allowed top-level fields are route_change, character_state, information_state, and
relationship_change. Do not include provider metadata, prompt text, or prose outside the object.
"""

__all__ = ["CUSTOM_ACTION_EFFECTS_PROMPT_V1"]
