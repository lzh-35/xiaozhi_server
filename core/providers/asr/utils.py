import re
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

EMOTION_EMOJI_MAP = {
    "HAPPY": "🙂",
    "SAD": "😔",
    "ANGRY": "😡",
    "NEUTRAL": "😶",
    "FEARFUL": "😰",
    "DISGUSTED": "🤢",
    "SURPRISED": "😲",
    "EMO_UNKNOWN": "😶",  # 未知情绪默认用中性表情
}
# EVENT_EMOJI_MAP = {
#     "<|BGM|>": "🎼",
#     "<|Speech|>": "",
#     "<|Applause|>": "👏",
#     "<|Laughter|>": "😀",
#     "<|Cry|>": "😭",
#     "<|Sneeze|>": "🤧",
#     "<|Breath|>": "",
#     "<|Cough|>": "🤧",
# }

def lang_tag_filter(text: str) -> dict | str:
    """
    解析 FunASR 识别结果，按顺序提取标签和纯文本内容

    Args:
        text: ASR 识别的原始文本，可能包含多种标签

    Returns:
        dict: {"language": "zh", "emotion": "SAD", "emoji": "😔", "content": "你好"} 如果有标签
        str: 纯文本，如果没有标签

    Examples:
        FunASR 输出格式：<|语种|><|情绪|><|事件|><|其他选项|>原文
        >>> lang_tag_filter("<|zh|><|SAD|><|Speech|><|withitn|>你好啊，测试测试。")
        {"language": "zh", "emotion": "SAD", "emoji": "😔", "content": "你好啊，测试测试。"}
        >>> lang_tag_filter("<|en|><|HAPPY|><|Speech|><|withitn|>Hello hello.")
        {"language": "en", "emotion": "HAPPY", "emoji": "🙂", "content": "Hello hello."}
        >>> lang_tag_filter("plain text")
        "plain text"
    """
    # 提取所有标签(按顺序)
    # r raw 原生的 r""：原始字符串，里面的 \ 不会被 Python 转义，正则专用写法
    # 在正则里是特殊符号，代表 “或”，想要匹配字面竖线必须加反斜杠转义，匹配固定开头 <|
    # \|>：转义竖线，匹配固定结尾 |>|
    # [^|]：^ 在中括号里代表取反，匹配任意不是竖线 | 的字符；
    # +：匹配 1 个及以上，不能是空
    # [] 是承载「禁止匹配竖线」规则的容器，没有方括号就写不出 “除了 | 以外所有字符” 这个逻辑
    tag_pattern = r"<\|([^|]+)\|>" # pattern 图案
    # 扫描全部文本，把所有匹配正则的捕获内容，全部收集到列表返回 re.findall() 提取函数
    all_tags = re.findall(tag_pattern, text) # 输出：["zh", "SAD", "Speech"]

    # 移除所有 <|...|> 格式的标签，获取纯文本 re.sub (正则，替换内容，文本) 替换删除函数
    clean_text = re.sub(tag_pattern, "", text).strip() # 输出：你好

    # 如果没有标签，直接返回纯文本
    if not all_tags:
        return clean_text

    # 按照 FunASR 的固定顺序提取标签，返回 dict
    language = all_tags[0] if len(all_tags) > 0 else "zh"
    emotion = all_tags[1] if len(all_tags) > 1 else "NEUTRAL"
    # event = all_tags[2] if len(all_tags) > 2 else "Speech"  # 事件标签暂不使用

    result = {
        "content": clean_text,
        "language": language,
        "emotion": emotion,
        # "event": event,
    }

    # 添加 emoji 映射
    if emotion in EMOTION_EMOJI_MAP:
        result["emotion"] = EMOTION_EMOJI_MAP[emotion]
    # 事件标签暂不使用
    # if event in EVENT_EMOJI_MAP:
    #     result["event"] = EVENT_EMOJI_MAP[event]

    return result

