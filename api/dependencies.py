"""FastAPI 依赖注入：Provider 单例 & QA Pipeline 工厂"""

from functools import lru_cache
# LRU = Least Recently Used 完整全称：Least Recently Used Cache 直译：最近最少使用缓存

from config.config_loader import load_config
from config.logger import setup_logging

logger = setup_logging()
TAG = __name__


# ───────────────────── Provider 工厂函数 ─────────────────────
# 直接复用 core/utils 下的工厂方法，保持与原有 WebSocket 服务一致


def _get_provider_type(config: dict, module_key: str) -> str:
    """从 selected_module 获取 provider 名称，再取实际 type"""
    provider_name = config["selected_module"].get(module_key, "")
    if not provider_name:
        raise ValueError(f"selected_module.{module_key} 未配置")
    provider_config = config.get(module_key, {}).get(provider_name, {})
    return provider_config.get("type", provider_name)


@lru_cache(maxsize=1)
def get_config() -> dict:
    """加载并缓存配置（进程生命周期内只加载一次）"""
    return load_config()


@lru_cache(maxsize=1)
def get_llm():
    """获取 LLM Provider 单例"""
    from core.utils.llm import create_instance as create_llm

    config = get_config()
    llm_name = config["selected_module"]["LLM"]
    llm_type = _get_provider_type(config, "LLM")
    logger.bind(tag=TAG).info(f"初始化 LLM: {llm_name} (type={llm_type})")
    return create_llm(llm_type, config["LLM"][llm_name])


@lru_cache(maxsize=1)
def get_asr():
    """获取 ASR Provider 单例"""
    from core.utils.asr import create_instance as create_asr

    config = get_config()
    asr_name = config["selected_module"]["ASR"]
    asr_type = _get_provider_type(config, "ASR")
    delete_audio = str(config.get("delete_audio", True)).lower() in ("true", "1", "yes")
    logger.bind(tag=TAG).info(f"初始化 ASR: {asr_name} (type={asr_type})")
    return create_asr(asr_type, config["ASR"][asr_name], delete_audio)


@lru_cache(maxsize=1)
def get_tts():
    """获取 TTS Provider 单例"""
    from core.utils.tts import create_instance as create_tts

    config = get_config()
    tts_name = config["selected_module"]["TTS"]
    tts_type = _get_provider_type(config, "TTS")
    delete_audio = str(config.get("delete_audio", True)).lower() in ("true", "1", "yes")
    logger.bind(tag=TAG).info(f"初始化 TTS: {tts_name} (type={tts_type})")
    return create_tts(tts_type, config["TTS"][tts_name], delete_audio)


# ───────────────────── Memory 工厂 ─────────────────────

def get_memory():
    """获取 Memory Provider（每次新建，避免 session 间状态污染）"""
    from core.utils import memory as memory_utils

    config = get_config()
    mem_name = config["selected_module"].get("Memory", "")
    if not mem_name:
        return None
    try:
        mem_type = _get_provider_type(config, "Memory")
        logger.bind(tag=TAG).info(f"初始化 Memory: {mem_name} (type={mem_type})")
        return memory_utils.create_instance(
            mem_type,
            config["Memory"][mem_name],
            config.get("summaryMemory", None),
        )
    except Exception as e:
        logger.bind(tag=TAG).warning(f"Memory 初始化失败（降级为无记忆）: {e}")
        return None


# ───────────────────── CRM 工厂 ─────────────────────

@lru_cache(maxsize=1)
def get_crm():
    """获取 CRM Provider 单例（SQLite，进程内共享连接池）"""
    from core.utils.crm import create_instance as create_crm

    config = get_config()
    crm_name = config["selected_module"].get("CRM", "")
    if not crm_name:
        logger.bind(tag=TAG).info("CRM 未配置，跳过")
        return None
    try:
        crm_type = _get_provider_type(config, "CRM")
        logger.bind(tag=TAG).info(f"初始化 CRM: {crm_name} (type={crm_type})")
        return create_crm(crm_type, config)
    except Exception as e:
        logger.bind(tag=TAG).warning(f"CRM 初始化失败: {e}")
        return None


# ───────────────────── Pipeline 工厂 ─────────────────────

def get_pipeline(session_id: str = "", client_ip: str = "", user_id: str = "") -> "QAPipeline":
    """创建 QAPipeline 实例（支持多轮对话）

    Args:
        session_id: 会话 ID（传已有 session_id 可继续对话）
        client_ip: 客户端 IP（用于位置感知等动态上下文）
        user_id: 用户标识（用于 CRM 用户画像）
    """
    from core.qa_pipeline import QAPipeline

    import uuid as _uuid

    config = get_config()
    sid = session_id or str(_uuid.uuid4().hex)

    intent_name = config["selected_module"].get("Intent", "nointent")
    intent_type = (
        config.get("Intent", {}).get(intent_name, {}).get("type", "nointent")
    )

    return QAPipeline(
        asr=get_asr(),
        llm=get_llm(),
        tts=get_tts(),
        config=config,
        memory=get_memory(),
        intent_type=intent_type,
        session_id=sid,
        client_ip=client_ip,
        crm=get_crm(),
        user_id=user_id,
    )
