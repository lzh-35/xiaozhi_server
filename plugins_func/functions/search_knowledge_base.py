"""
RAG 知识库检索插件

作为 LLM function calling 的一个工具，当用户询问产品手册、
FAQ、内部规则等知识库类问题时，LLM 自动调用此插件检索相关内容。

检索结果返回给 LLM 后，LLM 会结合 CRM 用户画像生成个性化回复。
"""

from config.logger import setup_logging
from plugins_func.register import register_function, ToolType, ActionResponse, Action

TAG = __name__
logger = setup_logging()

# ───────────────────── Function Calling 描述 ─────────────────────

SEARCH_KNOWLEDGE_BASE_DESC = {
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": (
            "从本地知识库中检索与用户问题相关的文档片段。"
            "适用于以下场景：\n"
            "1. 产品手册、使用说明、规格参数\n"
            "2. FAQ 常见问题\n"
            "3. 公司内部规则、政策、流程\n"
            "4. 课程介绍、服务条款等结构化知识\n\n"
            "当用户询问「xxx是什么」「xxx怎么用」「保修多久」「有什么课程」"
            "等知识库可覆盖的问题时，应优先调用此工具。"
            "注意：天气、新闻、实时信息请使用其他对应工具，不要用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "检索查询语句，应提取用户问题中的关键词，例如用户说「智能家居套餐的保修期是多久」，query 应为「智能家居套餐 保修期」",
                },
                "category": {
                    "type": "string",
                    "description": (
                        "可选，知识类别过滤。支持: 'product'(产品手册), 'faq'(常见问题), "
                        "'policy'(政策规则), 'course'(课程介绍)。不传则检索全部。"
                    ),
                },
            },
            "required": ["query"],
        },
    },
}


# ───────────────────── 插件函数 ─────────────────────


@register_function(
    "search_knowledge_base", SEARCH_KNOWLEDGE_BASE_DESC, ToolType.WAIT
)
def search_knowledge_base(query: str, category: str = None):
    """
    从本地知识库检索相关文档

    Args:
        query: 检索查询语句
        category: 可选，知识类别过滤

    Returns:
        ActionResponse with REQLLM action, 检索结果作为 context 返回给 LLM
    """
    from core.utils.rag import get_rag_manager

    try:
        rag = get_rag_manager()
        if rag is None:
            return ActionResponse(
                Action.REQLLM,
                None,
                "知识库暂不可用，请检查 RAG 配置（dashscope_api_key 和 knowledge_dir）。",
            )

        # 如果指定了 category，在 query 前加上类别限定
        search_query = query
        if category:
            search_query = f"[{category}] {query}"

        logger.bind(tag=TAG).info(
            f"RAG 检索: query={query}, category={category or 'all'}"
        )

        result = rag.search(search_query)

        if not result:
            return ActionResponse(
                Action.REQLLM,
                None,
                f"知识库中未找到与「{query}」相关的信息。请告知用户目前知识库暂无相关内容，建议联系客服或等待后续更新。",
            )

        # 将检索结果作为上下文返回，LLM 会基于此生成回复
        context = (
            f"以下是从知识库中检索到的与用户问题「{query}」相关的信息：\n\n"
            f"{result}\n\n"
            f"请基于以上信息回答用户问题，注意：\n"
            f"1. 如果信息不完整，请如实告知，不要编造\n"
            f"2. 结合用户画像（如果有）做个性化回复\n"
            f"3. 引用来源时使用文档名"
        )

        return ActionResponse(Action.REQLLM, context, None)

    except Exception as e:
        logger.bind(tag=TAG).error(f"RAG 检索异常: {e}")
        return ActionResponse(
            Action.REQLLM,
            None,
            f"知识库检索出错: {str(e)}",
        )
