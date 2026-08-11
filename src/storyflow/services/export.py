from __future__ import annotations

"""Markdown export for the current branch path."""

import re
from uuid import UUID

from storyflow.db.repositories import StoryRepository
from storyflow.domain.models import Story


def export_branch_markdown(repository: StoryRepository, story: Story) -> str:
    """Return a Markdown document for the story's current branch path."""
    cfg = story.config
    lines: list[str] = []

    # Title
    lines.append(f"# {story.title or '无题'}")
    lines.append("")

    # Settings summary
    lines.append("**创作设定**")
    lines.append("")
    lines.append(f"- 题材：{cfg.genre}")
    lines.append(f"- 结构：{cfg.structure}")
    lines.append(f"- 文风：{cfg.style}")
    if cfg.required_elements:
        lines.append(f"- 必须元素：{cfg.required_elements}")
    if cfg.forbidden_elements:
        lines.append(f"- 禁止元素：{cfg.forbidden_elements}")
    lines.append("")
    lines.append("---")
    lines.append("")

    if story.current_branch_id is None:
        return "\n".join(lines)

    segments = repository.list_branch_path(story.current_branch_id)
    for seg in segments:
        lines.append(f"## 场景 {seg.sequence}")
        lines.append("")
        lines.append(seg.content)
        lines.append("")

        # If this segment had a choice, show the selected option text (not effects)
        choice = repository.get_choice_point_for_segment(seg.id)
        if choice is not None and choice.status == "selected":
            if choice.selected_option_id is not None:
                option = next(
                    (o for o in choice.options if o.id == choice.selected_option_id),
                    None,
                )
                if option is not None:
                    lines.append(f"> **选择：** {option.text}")
                    lines.append("")
            elif choice.selected_custom_action:
                lines.append(f"> **自定义行动：** {choice.selected_custom_action}")
                lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def safe_filename(title: str) -> str:
    """Convert a story title to an ASCII-safe filename for HTTP headers."""
    # Keep only ASCII word chars and hyphens; Chinese chars become underscores
    cleaned = re.sub(r"[^\w\-]", "_", title.encode("ascii", errors="replace").decode("ascii"))
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned[:60] or "story"
