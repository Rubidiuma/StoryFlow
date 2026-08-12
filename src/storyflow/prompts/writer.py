"""Version-one prompt for writing one planned story scene."""

WRITER_PROMPT_ID = "scene_writer_v1"

WRITER_PROMPT_V1 = """[scene_writer_v1]
Write exactly one complete story scene in Chinese, based on the supplied context and ScenePlan.

OUTPUT FORMAT — follow exactly:
- Output ONLY raw Chinese prose. No JSON. No markdown. No headers.
- Use REAL Chinese punctuation: 「」or "" for dialogue, 。for period, etc.
- Do NOT escape any characters. Do NOT use \\n, \\", or any backslash sequences.
- Separate paragraphs with a blank line (press Enter twice).
- Write 500-800 Chinese characters total.

CRITICAL CHARACTER NAMES:
- Use EXACT character names as provided. NEVER translate names to English pinyin or phonetics.
- Always use: 蓝馨如 (not Lan Xinru, not 兰馨如)
- Check the character list for correct names before writing.

CONTENT RULES:
- Follow the scene beats in order.
- Close third-person perspective focused on the protagonist.
- Vivid, concrete action and sensory detail — show, don't tell.
- End at a natural stopping point before any choice moment.
- Do NOT include a choice menu or ask the reader to choose.
- Do NOT summarize — write the actual scene moment by moment.
"""

__all__ = ["WRITER_PROMPT_ID", "WRITER_PROMPT_V1"]
