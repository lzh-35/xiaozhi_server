"""
CRM 工厂方法

从配置中读取 CRM provider 并实例化。
"""

import importlib
import os
import sys


def create_instance(class_name: str, config: dict):
    """
    创建 CRM Provider 实例

    Args:
        class_name: provider 目录名，如 'crm_sqlite'
        config: 完整配置字典

    Returns:
        CRMProviderBase 实例
    """
    provider_path = os.path.join(
        "core", "providers", "crm", class_name, f"{class_name}.py"
    )
    if os.path.exists(provider_path):
        lib_name = f"core.providers.crm.{class_name}.{class_name}"
        if lib_name not in sys.modules:
            sys.modules[lib_name] = importlib.import_module(lib_name)
        return sys.modules[lib_name].CRMProvider(config)

    raise ValueError(f"不支持的 CRM 类型: {class_name}")
