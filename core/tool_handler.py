"""
简化工具处理器 — 专为 REST API 设计

- 使用轻量级 PipelineContext（替代旧的 ConnectionHandler）
- 仅处理服务端插件，插件函数通过 @register_function 自动注册
"""

import json
from typing import Dict, Any, List, Optional

from config.logger import setup_logging
from plugins_func.load_plugins import auto_import_modules
from plugins_func.register import (
    all_function_registry,
    Action,
    ActionResponse,
    ToolType,
)

TAG = __name__


class PipelineContext:
    """轻量级上下文，供插件函数使用

    插件函数通过 self.context 访问 config、session_id、dialogue、logger。
    """

    def __init__(
        self,
        config: dict,
        session_id: str,
        dialogue=None,  # core.utils.dialogue.Dialogue
        logger=None,
        client_ip: str = "127.0.0.1",
    ):
        self.config = config
        self.session_id = session_id
        self.dialogue = dialogue
        self.logger = logger or setup_logging()
        self.client_ip = client_ip
        # 以下属性供特定插件使用
        self.close_after_chat = False


class SimplifiedToolHandler:
    """简化工具处理器 — 仅处理服务端插件"""

    def __init__(self, context: PipelineContext):
        self.context = context
        self.config = context.config
        self.logger = context.logger

        # 自动导入插件模块 → 触发 @register_function 装饰器
        auto_import_modules("plugins_func.functions")

    # ------------------------------------------------------------------
    # 工具描述（供 LLM function calling 使用）
    # ------------------------------------------------------------------

    def get_functions(self) -> List[Dict[str, Any]]:
        """获取已注册的函数描述列表 (OpenAI function calling 格式)"""
        func_names = self._get_enabled_function_names()
        functions = []
        for name in func_names:
            func_item = all_function_registry.get(name)
            if func_item and isinstance(func_item.description, dict):
                desc = func_item.description.copy()
                # 注入运行时 description（如果配置中有覆盖）
                custom_desc = (
                    self.config.get("plugins", {})
                    .get(name, {})
                    .get("description", "")
                )
                if custom_desc and "function" in desc:
                    desc["function"]["description"] = custom_desc
                functions.append(desc)
        return functions

    def _get_enabled_function_names(self) -> List[str]:
        """从配置中获取启用的函数名列表"""
        intent_config = self.config.get("Intent", {})
        selected = self.config.get("selected_module", {}).get("Intent", "")
        functions_cfg = intent_config.get(selected, {}).get("functions", [])
        if not isinstance(functions_cfg, list):
            functions_cfg = list(functions_cfg) if functions_cfg else []
        return list(functions_cfg) if functions_cfg else []

    # ------------------------------------------------------------------
    # 工具执行
    # ------------------------------------------------------------------

    async def execute_tool(
        self, tool_name: str, arguments: Dict[str, Any]
    ) -> ActionResponse:
        """执行一个工具调用"""
        func_item = all_function_registry.get(tool_name)
        if not func_item:
            self.logger.bind(tag=TAG).warning(f"插件函数 {tool_name} 不存在")
            return ActionResponse(
                action=Action.NOTFOUND,
                response=f"插件函数 {tool_name} 不存在",
            )

        try:
            # 根据工具类型决定是否传 context
            if hasattr(func_item, "type") and func_item.type is not None:
                func_type = func_item.type
                if func_type.code in [4, 5, 3]:
                    # SYSTEM_CTL, IOT_CTL, CHANGE_SYS_PROMPT → 需要 context
                    result = func_item.func(self.context, **arguments)
                else:
                    result = func_item.func(**arguments)
            else:
                result = func_item.func(**arguments)

            return result

        except Exception as e:
            self.logger.bind(tag=TAG).error(f"工具 {tool_name} 执行失败: {e}")
            return ActionResponse(action=Action.ERROR, response=str(e))

    # ------------------------------------------------------------------
    # 工具调用处理（LLM function calling 响应 → 执行 → 返回结果）
    # ------------------------------------------------------------------

    async def handle_llm_function_call(
        self, function_call_data: Dict[str, Any]
    ) -> Optional[ActionResponse]:
        """处理 LLM 的 function call 响应"""
        function_name = function_call_data.get("name", "")
        arguments = function_call_data.get("arguments", {})

        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                return ActionResponse(
                    action=Action.ERROR,
                    response="无法解析函数参数",
                )

        self.logger.bind(tag=TAG).info(
            f"执行工具: {function_name}, 参数: {arguments}"
        )
        return await self.execute_tool(function_name, arguments)
