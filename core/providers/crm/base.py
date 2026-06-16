"""
CRM Provider 抽象基类

定义用户画像管理、对话记录的标准接口。
所有 CRM 实现（SQLite / 外部 API）必须继承此类。
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, List, Any
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()


class CRMProviderBase(ABC):
    """CRM 用户画像 & 对话记录 抽象基类"""

    def __init__(self, config: dict):
        self.config = config
        self.logger = logger

    # ------------------------------------------------------------------
    # 用户画像
    # ------------------------------------------------------------------

    @abstractmethod
    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        查询用户画像

        Args:
            user_id: 用户标识（手机号 / 自定义 ID）

        Returns:
            {
                "user_id": "138xxxx",
                "name": "张三",
                "phone": "138xxxx",
                "tags": ["VIP客户", "高净值"],
                "profile": {
                    "preferences": {...},
                    "purchased": [...],
                    ...
                },
                "created_at": "2025-01-01 12:00:00",
                "updated_at": "2025-06-16 10:00:00",
            }
            用户不存在时返回 None
        """
        ...

    @abstractmethod
    def create_or_update_user(
        self,
        user_id: str,
        name: str = "",
        phone: str = "",
        tags: Optional[List[str]] = None,
        profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """创建或更新用户信息，返回最新用户画像"""
        ...

    @abstractmethod
    def update_user_from_conversation(
        self,
        user_id: str,
        query: str = "",
        response: str = "",
        intent: str = "",
        profile_delta: Optional[Dict[str, Any]] = None,
    ):
        """
        从对话中提取关键信息，增量更新用户画像（闭环）

        Args:
            user_id: 用户标识
            query: 用户问题
            response: 系统回复
            intent: 意图分类
            profile_delta: LLM 提取的结构化画像增量（identity/interests/facts/sentiment）
        """
        ...

    # ------------------------------------------------------------------
    # 对话记录
    # ------------------------------------------------------------------

    @abstractmethod
    def save_conversation(
        self,
        user_id: str,
        session_id: str,
        query: str,
        response: str,
        intent: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        """保存一条对话记录"""
        ...

    @abstractmethod
    def get_conversation_history(
        self, user_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        """获取用户最近对话历史"""
        ...

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def close(self):
        """关闭连接（子类可覆盖）"""
        pass
