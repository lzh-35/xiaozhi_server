"""
CRM REST API 路由

提供用户画像查询、用户创建、对话历史查看等接口。
"""

from fastapi import APIRouter, HTTPException
from api.schemas import (
    CRMCreateUserRequest,
    CRMUserProfile,
    CRMConversationItem,
    CRMUserHistoryResponse,
    ErrorResponse,
)
from api.dependencies import get_crm, get_config

router = APIRouter(prefix="/crm", tags=["CRM"])


# ───────────────────── GET /crm/users/{user_id} ─────────────────────


@router.get(
    "/users/{user_id}",
    response_model=CRMUserHistoryResponse,
    summary="查询用户完整档案",
    description="获取用户画像 + 最近20条对话历史",
)
async def get_user_profile(user_id: str):
    """查询用户完整档案（画像 + 对话历史）"""
    crm = get_crm()
    if crm is None:
        raise HTTPException(status_code=503, detail="CRM 未启用，请检查配置")

    profile = crm.get_user_profile(user_id)
    conversations = crm.get_conversation_history(user_id, limit=20)

    if profile is None:
        return CRMUserHistoryResponse(
            profile=None,
            conversations=[
                CRMConversationItem(**conv) for conv in conversations
            ],
        )

    return CRMUserHistoryResponse(
        profile=CRMUserProfile(**profile),
        conversations=[
            CRMConversationItem(**conv) for conv in conversations
        ],
    )


# ───────────────────── POST /crm/users ─────────────────────


@router.post(
    "/users",
    response_model=CRMUserProfile,
    summary="创建/更新用户",
    description="创建新用户或更新已有用户的信息（姓名、标签、画像等）",
)
async def create_or_update_user(req: CRMCreateUserRequest):
    """创建或更新 CRM 用户"""
    crm = get_crm()
    if crm is None:
        raise HTTPException(status_code=503, detail="CRM 未启用，请检查配置")

    result = crm.create_or_update_user(
        user_id=req.user_id,
        name=req.name,
        phone=req.phone or req.user_id,
        tags=req.tags,
        profile=req.profile,
    )
    return CRMUserProfile(**result)


# ───────────────────── GET /crm/users/{user_id}/conversations ─────────────────────


@router.get(
    "/users/{user_id}/conversations",
    response_model=list[CRMConversationItem],
    summary="查询用户对话历史",
    description="获取指定用户最近 N 条对话记录（默认20条）",
)
async def get_user_conversations(user_id: str, limit: int = 20):
    """查询用户对话历史"""
    crm = get_crm()
    if crm is None:
        raise HTTPException(status_code=503, detail="CRM 未启用，请检查配置")

    conversations = crm.get_conversation_history(user_id, limit=min(limit, 100))
    return [CRMConversationItem(**conv) for conv in conversations]


# ───────────────────── GET /crm/health ─────────────────────


@router.get(
    "/health",
    summary="CRM 健康检查",
    description="检查 CRM 服务是否可用",
)
async def crm_health():
    """CRM 模块健康检查"""
    crm = get_crm()
    if crm is None:
        return {"status": "disabled", "message": "CRM 未配置（selected_module.CRM 为空）"}
    return {"status": "ok", "db_path": getattr(crm, "db_path", "N/A")}


# ───────────────────── GET /crm/knowledge ─────────────────────


@router.get(
    "/knowledge",
    summary="RAG 知识库信息",
    description="查看知识库索引状态（文档数、块数等）",
)
async def knowledge_base_info():
    """查看知识库状态"""
    from core.utils.rag import get_rag_manager

    rag = get_rag_manager()
    if rag is None:
        return {"status": "disabled", "message": "RAG 未初始化，请检查 dashscope_api_key 配置"}

    try:
        collection = rag.vectorstore._collection
        count = collection.count()
        return {
            "status": "ok",
            "persist_dir": rag.persist_dir,
            "knowledge_dir": rag.knowledge_dir,
            "chunk_count": count,
            "chunk_size": rag.chunk_size,
            "top_k": rag.top_k,
            "embedding_model": "text-embedding-v4",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.post(
    "/knowledge/reload",
    summary="重建知识库索引",
    description="强制重新加载知识库文档并重建向量索引",
)
async def reload_knowledge():
    """强制重建知识库索引"""
    from core.utils.rag import get_rag_manager

    rag = get_rag_manager()
    if rag is None:
        raise HTTPException(status_code=503, detail="RAG 未初始化")

    try:
        rag.reload()
        return {"status": "ok", "message": "知识库索引已重建"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重建失败: {str(e)}")
