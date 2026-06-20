"""通用工具函数"""


def check_model_key(model_type: str, model_key: str) -> str | None:
    """检查 API key 是否已配置"""
    if "你" in model_key:
        return f"配置错误: {model_type} 的 API key 未设置, 当前值为: {model_key}"
    return None
