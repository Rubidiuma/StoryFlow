"""Protagonist name extraction and generation."""

import random
import re
from typing import Optional


# Common Chinese surnames
SURNAMES = [
    "李", "王", "张", "刘", "陈", "杨", "黄", "赵", "周", "徐",
    "孙", "马", "朱", "林", "高", "郭", "何", "吴", "邱", "曾",
    "萧", "程", "曹", "韦", "唐", "许", "邓", "冯", "曾", "彭",
    "蓝", "白", "范", "方", "石", "崔", "任", "樊", "汪", "关",
]

# Common Chinese given name characters
GIVEN_NAMES = [
    "馨", "如", "明", "芳", "娟", "红", "霞", "丽", "敏", "亮",
    "强", "光", "伟", "刚", "杰", "岗", "凯", "锋", "鹏", "宇",
    "雨", "涛", "波", "浩", "云", "风", "雪", "月", "星", "阳",
    "鑫", "欣", "心", "思", "梦", "希", "怡", "妍", "莉", "琳",
]


def extract_protagonist_name(description: str) -> Optional[str]:
    """Extract protagonist name from the description if mentioned.

    Examples:
    - "韩立是一个修仙者" → "韩立"
    - "李明渴望冒险" → "李明"
    - "一个普通人发现了超能力" → None
    """
    if not description or not isinstance(description, str):
        return None

    # Try multiple patterns to find the protagonist name
    patterns = [
        # Pattern 1: Name at the beginning followed by "是" (e.g., "蓝馨如是一个修仙者")
        r'^([一-鿿]{2,4})[是]',
        # Pattern 2: Name after "叫/名字是/叫做" (e.g., "主角叫张三")
        r'(?:叫|名字是|叫做)[\s]?([一-鿿]{2,4})',
        # Pattern 3: Name followed by "是主角/是女主/是男主"
        r'([一-鿿]{2,4})(?:是|为)(?:主角|女主|男主)',
    ]

    for pattern in patterns:
        match = re.search(pattern, description)
        if match:
            name = match.group(1)
            if _is_valid_chinese_name(name):
                return name

    return None


def _is_valid_chinese_name(name: str) -> bool:
    """Check if a string looks like a valid Chinese name."""
    if not name or len(name) < 2 or len(name) > 4:
        return False

    # Check if all characters are CJK
    return all('一' <= c <= '鿿' for c in name)


def generate_random_protagonist_name() -> str:
    """Generate a random Chinese name for the protagonist.

    Returns a name with 2-3 characters (surname + 1-2 given names).
    """
    surname = random.choice(SURNAMES)
    num_given = random.choice([1, 2])
    given = ''.join(random.choice(GIVEN_NAMES) for _ in range(num_given))
    return surname + given


def get_protagonist_name(description: str) -> str:
    """Get or generate protagonist name from description.

    Returns:
    - The extracted name if found in description
    - A randomly generated name otherwise
    """
    extracted = extract_protagonist_name(description)
    if extracted:
        return extracted
    return generate_random_protagonist_name()
