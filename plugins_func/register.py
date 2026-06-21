from config.logger import setup_logging
from enum import Enum

TAG = __name__

logger = setup_logging()


class ToolType(Enum):
    NONE = (1, "调用完工具后，不做其他操作")
    WAIT = (2, "调用工具，等待函数返回")
    CHANGE_SYS_PROMPT = (3, "修改系统提示词，切换角色性格或职责")
    SYSTEM_CTL = (4, "系统控制，需要传递 context 参数")
    IOT_CTL = (5, "IOT 设备控制，需要传递 context 参数")

    def __init__(self, code, message):
        self.code = code
        self.message = message


class Action(Enum):
    ERROR = (-1, "错误")
    NOTFOUND = (0, "没有找到函数")
    NONE = (1, "啥也不干")
    RESPONSE = (2, "直接回复")
    REQLLM = (3, "调用函数后再请求llm生成回复")
    RECORD = (4, "记录工具调用到对话历史，不调用LLM")

    def __init__(self, code, message):
        self.code = code
        self.message = message


class ActionResponse:
    def __init__(self, action: Action, result=None, response=None):
        self.action = action  # 动作类型
        self.result = result  # 动作产生的结果
        self.response = response  # 直接回复的内容


class FunctionItem:
    def __init__(self, name, description, func, type):
        self.name = name
        self.description = description
        self.func = func
        self.type = type


# 全局函数注册字典
all_function_registry = {}


def register_function(name, desc, type=None):
    """注册函数到全局注册字典的装饰器"""

    def decorator(func):
        all_function_registry[name] = FunctionItem(name, desc, func, type)
        logger.bind(tag=TAG).debug(f"函数 '{name}' 已加载")
        return func

    return decorator
