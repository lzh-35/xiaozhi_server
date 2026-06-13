import os
import re
import sys
import importlib

from config.logger import setup_logging
from core.utils.textUtils import check_emoji

logger = setup_logging()

# punctuation 标点符号
punctuation_set = {
    "，",
    ",",  # 中文逗号 + 英文逗号
    "。",
    ".",  # 中文句号 + 英文句号
    "！",
    "!",  # 中文感叹号 + 英文感叹号
    "“",
    "”",
    '"',  # 中文双引号 + 英文引号
    "：",
    ":",  # 中文冒号 + 英文冒号
    "-",
    "－",  # 英文连字符 + 中文全角横线
    "、",  # 中文顿号
    "[",
    "]",  # 方括号
    "【",
    "】",  # 中文方括号
    "~",  # 波浪号
}

# *args 将多余位置参数打包成元组 args = ( {"type": "edge", "voice": "...", "output_dir": "tmp/"}, True )
# **kwargs 接收关键字参数，此处没有，所以 kwargs = {}
def create_instance(class_name, *args, **kwargs):
    # 创建TTS实例
    if os.path.exists(os.path.join('core', 'providers', 'tts', f'{class_name}.py')):
        # 动态导入 相当于 from core.providers.tts import edge_tts
        lib_name = f'core.providers.tts.{class_name}'
        if lib_name not in sys.modules:
            # sys.modules 是 Python 的一个全局字典（内置模块 sys 的属性），它缓存了所有已经导入过的模块
            # 你执行 import os 后，Python 内部就会在 sys.modules 中添加一项：{'os': <module 'os'>}
            # 它的作用是避免重复导入同一个模块，提高效率
            # import os # 静态导入等价于：os = importlib.import_module('os')

            # module = importlib.import_module(lib_name) 更常见的写法
            # sys.modules 中已经自动有了这个模块，不用再赋值

            # importlib.import_module(lib_name) 动态导入 lib_name
            # 对应的模块（例如'core.providers.tts.edge_tts'），并返回该模块对象。
            # 然后把返回的模块对象手动存入 sys.modules字典，键就是模块名 lib_name
            sys.modules[lib_name] = importlib.import_module(f'{lib_name}')

            # 最后无论是否新导入，都从 sys.modules 取出模块，并获取其 TTSProvider 类来实例化

        # 最终，TTSProvider 的构造函数会收到：
        # 第一个参数：配置字典 {"type": "edge", "voice": "...", "output_dir": "tmp/"}
        # 第二个参数：布尔值 True（表示删除临时音频）
        return sys.modules[lib_name].TTSProvider(*args, **kwargs)

    raise ValueError(f"不支持的TTS类型: {class_name}，请检查该配置的type是否设置正确")


class MarkdownCleaner:
    """
    封装 Markdown 清理逻辑：直接用 MarkdownCleaner.clean_markdown(text) 即可
    """
    # 公式字符
    NORMAL_FORMULA_CHARS = re.compile(r'[a-zA-Z\\^_{}\+\-\(\)\[\]=]')

    @staticmethod
    def _replace_inline_dollar(m: re.Match) -> str:
        """
        只要捕获到完整的 "$...$":
          - 如果内部有典型公式字符 => 去掉两侧 $
          - 否则 (纯数字/货币等) => 保留 "$...$"
        """
        content = m.group(1)
        if MarkdownCleaner.NORMAL_FORMULA_CHARS.search(content):
            return content
        else:
            return m.group(0)

    @staticmethod
    def _replace_table_block(match: re.Match) -> str:
        """
        当匹配到一个整段表格块时，回调该函数。
        """
        block_text = match.group('table_block')
        lines = block_text.strip('\n').split('\n')

        parsed_table = []
        for line in lines:
            line_stripped = line.strip()
            if re.match(r'^\|\s*[-:]+\s*(\|\s*[-:]+\s*)+\|?$', line_stripped):
                continue
            columns = [col.strip() for col in line_stripped.split('|') if col.strip() != '']
            if columns:
                parsed_table.append(columns)

        if not parsed_table:
            return ""

        headers = parsed_table[0]
        data_rows = parsed_table[1:] if len(parsed_table) > 1 else []

        lines_for_tts = []
        if len(parsed_table) == 1:
            # 只有一行
            only_line_str = ", ".join(parsed_table[0])
            lines_for_tts.append(f"单行表格：{only_line_str}")
        else:
            lines_for_tts.append(f"表头是：{', '.join(headers)}")
            for i, row in enumerate(data_rows, start=1):
                row_str_list = []
                for col_index, cell_val in enumerate(row):
                    if col_index < len(headers):
                        row_str_list.append(f"{headers[col_index]} = {cell_val}")
                    else:
                        row_str_list.append(cell_val)
                lines_for_tts.append(f"第 {i} 行：{', '.join(row_str_list)}")

        return "\n".join(lines_for_tts) + "\n"

    # 预编译所有正则表达式（按执行频率排序）
    # 这里要把 replace_xxx 的静态方法放在最前定义，以便在列表里能正确引用它们。
    REGEXES = [
        (re.compile(r'```.*?```', re.DOTALL), ''),  # 代码块
        (re.compile(r'^#+\s*', re.MULTILINE), ''),  # 标题
        (re.compile(r'(\*\*|__)(.*?)\1'), r'\2'),  # 粗体
        (re.compile(r'(\*|_)(?=\S)(.*?)(?<=\S)\1'), r'\2'),  # 斜体
        (re.compile(r'!\[.*?\]\(.*?\)'), ''),  # 图片
        (re.compile(r'\[(.*?)\]\(.*?\)'), r'\1'),  # 链接
        (re.compile(r'^\s*>+\s*', re.MULTILINE), ''),  # 引用
        (
            re.compile(r'(?P<table_block>(?:^[^\n]*\|[^\n]*\n)+)', re.MULTILINE),
            _replace_table_block
        ),
        (re.compile(r'^\s*[*+-]\s*', re.MULTILINE), '- '),  # 列表
        (re.compile(r'\$\$.*?\$\$', re.DOTALL), ''),  # 块级公式
        (
            re.compile(r'(?<![A-Za-z0-9])\$([^\n$]+)\$(?![A-Za-z0-9])'),
            _replace_inline_dollar
        ),
        (re.compile(r'\n{2,}'), '\n'),  # 多余空行
    ]

    @staticmethod
    def clean_markdown(text: str) -> str:
        """
        主入口方法：依序执行所有正则，移除或替换 Markdown 元素
        """
        for regex, replacement in MarkdownCleaner.REGEXES:
            text = regex.sub(replacement, text)

        # 去除emoji表情
        text = check_emoji(text)

        # 检查文本是否全为英文和基本标点符号
        if text and all((c.isascii() or c.isspace() or c in punctuation_set) for c in text):
            # 保留原始空格，直接返回
            return text

        return text.strip()

def convert_percentage_to_range(percentage, min_val, max_val, base_val=None):
    """
    将百分比(-100~100)转换为指定范围的值

    Args:
        percentage: 百分比值 (-100 到 100)
        min_val: 目标范围最小值
        max_val: 目标范围最大值
        base_val: 基准值（可选，默认为范围中点）

    Returns:
        转换后的值
    """
    percentage, min_val, max_val = float(percentage), float(min_val), float(max_val)
    base_val = float(base_val) if base_val is not None else (min_val + max_val) / 2

    if percentage < 0:
        # 负百分比：从 base_val 向 min_val 线性插值
        result = base_val + (base_val - min_val) * (percentage / 100)
    else:
        # 正百分比：从 base_val 向 max_val 线性插值
        result = base_val + (max_val - base_val) * (percentage / 100)

    # 确保结果在有效范围内
    return max(min_val, min(max_val, result))
