"""文本处理工具 — emoji 检测 & 标点符号集合"""

# 需要去除的标点符号集合（tts.py 也复用此定义）
PUNCTUATION_SET = {
    "，", ",",      # 中文逗号 + 英文逗号
    "。", ".",      # 中文句号 + 英文句号
    "！", "!",      # 中文感叹号 + 英文感叹号
    "“", "”", '"', # 中文双引号 + 英文引号
    "：", ":",      # 中文冒号 + 英文冒号
    "-", "－",      # 英文连字符 + 中文全角横线
    "、",           # 中文顿号
    "[", "]",       # 方括号
    "【", "】",     # 中文方括号
    "~",            # 波浪号
}

EMOJI_RANGES = [
    (0x1F600, 0x1F64F),
    (0x1F300, 0x1F5FF),
    (0x1F680, 0x1F6FF),
    (0x1F900, 0x1F9FF),
    (0x1FA70, 0x1FAFF),
    (0x2600, 0x26FF),
    (0x2700, 0x27BF),
]


def is_emoji(char: str) -> bool:
    """检查字符是否为 emoji"""
    code_point = ord(char)
    return any(start <= code_point <= end for start, end in EMOJI_RANGES)


def check_emoji(text: str) -> str:
    """去除文本中所有 emoji 和换行符"""
    return "".join(char for char in text if not is_emoji(char) and char != "\n")
