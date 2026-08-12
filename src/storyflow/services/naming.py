"""Protagonist name extraction and generation."""

import random
import re
from typing import Optional


# Complete Chinese surnames from 《百家姓》
SURNAMES = [
    "赵", "钱", "孙", "李", "周", "吴", "郑", "王", "冯", "陈",
    "褚", "卫", "蒋", "沈", "韩", "杨", "朱", "秦", "尤", "许",
    "何", "吕", "施", "张", "孔", "曹", "严", "华", "金", "魏",
    "陶", "姜", "戚", "谢", "邹", "喜", "祝", "滑", "夏", "徐",
    "韦", "昌", "马", "苗", "凤", "花", "草", "唐", "费", "廉",
    "岑", "薛", "雷", "贺", "倪", "汤", "滕", "殷", "罗", "毕",
    "郝", "邬", "安", "常", "乐", "于", "时", "傅", "皮", "卞",
    "齐", "康", "伍", "余", "元", "卜", "顾", "孟", "平", "黄",
    "和", "穆", "萧", "尹", "姚", "邵", "湛", "汪", "祁", "毛",
    "禾", "丘", "有", "邳", "幸", "党", "宫", "宁", "宓", "牛",
    "寿", "通", "边", "扈", "燕", "冀", "郦", "雍", "舄", "聂",
    "晋", "楚", "闫", "法", "汝", "鄞", "益", "桓", "公", "晁",
    "丘", "金", "陆", "荣", "翁", "晋", "盛", "虞", "卓", "闻",
    "莫", "娄", "经", "房", "裘", "缑", "亢", "况", "郈", "聊",
    "尚", "庄", "栗", "巩", "糜", "舒", "只", "阚", "贲", "怀",
    "寇", "能", "尔", "向", "戎", "席", "廖", "庚", "终", "暨",
    "居", "衡", "步", "都", "耿", "满", "弘", "匡", "国", "文",
    "寸", "禄", "东", "殖", "养", "鞠", "丰", "井", "段", "巴",
    "丛", "神", "禄", "夫", "武", "符", "王", "晨", "栋", "川",
    "州", "工", "左", "史", "钟", "宗", "丘", "金", "主", "孙",
]

# Common Chinese given name characters (from various classical sources)
GIVEN_NAMES = [
    # Virtues and character traits
    "馨", "伟", "明", "芳", "娟", "红", "霞", "丽", "敏", "亮",
    "强", "光", "如", "刚", "杰", "岗", "凯", "锋", "鹏", "宇",
    "雨", "涛", "波", "浩", "云", "风", "雪", "月", "星", "阳",
    "鑫", "欣", "心", "思", "梦", "希", "怡", "妍", "莉", "琳",
    # More contemporary names
    "文", "武", "俊", "英", "华", "忠", "义", "勇", "智", "仁",
    "诗", "书", "礼", "乐", "德", "贤", "秀", "雅", "静", "柔",
    "金", "玉", "石", "琳", "瑞", "祥", "茂", "盛", "昌", "荣",
    "泽", "润", "滨", "江", "河", "林", "森", "竹", "梅", "兰",
    "菊", "荷", "桃", "李", "杏", "柳", "樱", "枫", "松", "柏",
    "娥", "嫦", "姝", "媛", "婉", "柔", "倩", "漫", "羽", "翔",
    "彤", "玟", "岚", "萱", "曼", "琦", "瑾", "瑶", "瑛", "琼",
    "轩", "逸", "浩", "博", "羽", "翔", "志", "昂", "升", "鹰",
    "墨", "岳", "云", "枫", "桦", "樾", "渊", "澜", "瀚", "澜",
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
