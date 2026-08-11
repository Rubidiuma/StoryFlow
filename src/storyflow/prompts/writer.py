"""Version-one prompt for writing one planned story scene."""

WRITER_PROMPT_ID = "scene_writer_v1"

WRITER_PROMPT_V1 = """[scene_writer_v1]
Write exactly one complete story scene in Chinese, based on the supplied context and ScenePlan.

Rules:
- Write 500-800 Chinese characters of story prose.
- Follow the scene beats in order.
- Use close third-person perspective focused on the protagonist.
- Write vivid, concrete action and sensory detail — show, don't tell.
- End the scene at a natural stopping point (before any choice).
- Do NOT include a choice menu, JSON, headers, or commentary.
- Do NOT summarize what happens — write the actual scene.
- Use paragraph breaks (blank lines) to separate paragraphs.
"""

__all__ = ["WRITER_PROMPT_ID", "WRITER_PROMPT_V1"]
