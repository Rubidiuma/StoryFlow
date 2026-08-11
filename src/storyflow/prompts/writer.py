"""Version-one prompt for writing one planned story scene."""

WRITER_PROMPT_ID = "scene_writer_v1"

WRITER_PROMPT_V1 = """[scene_writer_v1]
Write exactly one complete story scene from the supplied context and validated ScenePlan.
Return story prose only. Follow the plan in order and do not emit JSON, commentary, or a
choice menu.
"""

__all__ = ["WRITER_PROMPT_ID", "WRITER_PROMPT_V1"]
