"""
SQLite CRM Provider 实现

用户画像 + 对话记录持久化到本地 SQLite。
每次对话后自动更新用户画像，形成闭环。
"""

import os
import json
import sqlite3
import time
from typing import Optional, Dict, List, Any

from ..base import CRMProviderBase

TAG = __name__

# 数据库 DDL
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id     TEXT PRIMARY KEY,
    name        TEXT DEFAULT '',
    phone       TEXT DEFAULT '',
    tags        TEXT DEFAULT '[]',       -- JSON array
    profile     TEXT DEFAULT '{}',       -- JSON object (用户画像)
    created_at  TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS conversations (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    session_id  TEXT NOT NULL,
    query       TEXT DEFAULT '',
    response    TEXT DEFAULT '',
    intent      TEXT DEFAULT '',
    metadata    TEXT DEFAULT '{}',       -- JSON object
    created_at  TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_conv_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_conv_session_id ON conversations(session_id);
CREATE INDEX IF NOT EXISTS idx_conv_created_at ON conversations(created_at);
"""


class CRMProvider(CRMProviderBase):
    """SQLite CRM 实现"""

    def __init__(self, config: dict):
        super().__init__(config)
        crm_config = config.get("crm", {})
        db_path = crm_config.get("db_path", "data/crm.db")
        # 确保路径相对于项目根目录
        if not os.path.isabs(db_path):
            from config.config_loader import get_project_dir
            db_path = os.path.join(get_project_dir(), db_path)
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    # ------------------------------------------------------------------
    # 数据库初始化
    # ------------------------------------------------------------------

    def _init_db(self):
        """初始化数据库表结构"""
        try:
            with self._get_conn() as conn:
                conn.executescript(SCHEMA_SQL)
                conn.commit()
            self.logger.bind(tag=TAG).info(f"CRM 数据库已就绪: {self.db_path}")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"CRM 数据库初始化失败: {e}")

    def _get_conn(self) -> sqlite3.Connection:
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ------------------------------------------------------------------
    # 用户画像
    # ------------------------------------------------------------------

    def get_user_profile(self, user_id: str) -> Optional[Dict[str, Any]]:
        if not user_id:
            return None
        try:
            with self._get_conn() as conn:
                row = conn.execute(
                    "SELECT * FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()
            if row is None:
                return None
            return self._row_to_user_dict(row)
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"查询用户画像失败: {e}")
            return None

    def create_or_update_user(
        self,
        user_id: str,
        name: str = "",
        phone: str = "",
        tags: Optional[List[str]] = None,
        profile: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            now = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            tags_json = json.dumps(tags or [], ensure_ascii=False)
            profile_json = json.dumps(profile or {}, ensure_ascii=False)

            with self._get_conn() as conn:
                existing = conn.execute(
                    "SELECT user_id FROM users WHERE user_id = ?", (user_id,)
                ).fetchone()

                if existing:
                    # 更新现有用户
                    updates = []
                    params = []
                    if name:
                        updates.append("name = ?")
                        params.append(name)
                    if phone:
                        updates.append("phone = ?")
                        params.append(phone)
                    if tags is not None:
                        updates.append("tags = ?")
                        params.append(tags_json)
                    if profile is not None:
                        updates.append("profile = ?")
                        params.append(profile_json)
                    updates.append("updated_at = ?")
                    params.append(now)
                    params.append(user_id)

                    conn.execute(
                        f"UPDATE users SET {', '.join(updates)} WHERE user_id = ?",
                        params,
                    )
                else:
                    # 新建用户
                    conn.execute(
                        """INSERT INTO users (user_id, name, phone, tags, profile, created_at, updated_at)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (user_id, name, phone or user_id, tags_json, profile_json, now, now),
                    )
                conn.commit()

            return self.get_user_profile(user_id) or {}
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"创建/更新用户失败: {e}")
            return {}

    def update_user_from_conversation(
        self,
        user_id: str,
        query: str = "",
        response: str = "",
        intent: str = "",
        profile_delta=None,
    ):
        """
        从对话中提取关键信息，增量更新用户画像。

        策略：
        - 应用 LLM 提取的 profile_delta（identity/interests/facts/sentiment）
        - 记录用户关注的高频话题
        - 记录最近活跃时间
        - 新用户自动注册
        """
        if not user_id:
            return

        try:
            profile = self.get_user_profile(user_id)
            if profile is None:
                # 新用户，自动注册
                self.create_or_update_user(user_id=user_id, phone=user_id)
                profile = self.get_user_profile(user_id) or {}

            profile_data = profile.get("profile", {})
            if isinstance(profile_data, str):
                try:
                    profile_data = json.loads(profile_data)
                except (json.JSONDecodeError, TypeError):
                    profile_data = {}

            tags = profile.get("tags", [])
            if isinstance(tags, str):
                try:
                    tags = json.loads(tags)
                except (json.JSONDecodeError, TypeError):
                    tags = []

            name = profile.get("name", "")

            # ── 应用 LLM 提取的 profile_delta ──
            if profile_delta and isinstance(profile_delta, dict):
                # 身份信息
                identity = profile_delta.get("identity", {})
                if identity.get("name") and not name:
                    name = identity["name"]

                # 会员等级 → 标签
                member = identity.get("member_level", "")
                if member and member not in tags:
                    tags.append(member)

                # 合并 facts
                facts = profile_delta.get("facts", {})
                if facts:
                    stored_facts = profile_data.get("facts", {})
                    if isinstance(stored_facts, dict):
                        stored_facts.update(facts)
                    else:
                        stored_facts = facts
                    profile_data["facts"] = stored_facts

                # 合并 interests（去重）
                interests = profile_delta.get("interests", [])
                if interests:
                    stored_interests = profile_data.get("interests", [])
                    if not isinstance(stored_interests, list):
                        stored_interests = []
                    for interest in interests:
                        if interest not in stored_interests:
                            stored_interests.append(interest)
                    profile_data["interests"] = stored_interests

                # 最近意图
                intents = profile_delta.get("intents", [])
                if intents:
                    profile_data["last_intents"] = intents

                # 情感记录
                sentiment = profile_delta.get("sentiment", {})
                if sentiment:
                    history = profile_data.get("sentiment_history", [])
                    if not isinstance(history, list):
                        history = []
                    history.append({
                        "polarity": sentiment.get("polarity", "neutral"),
                        "confidence": sentiment.get("confidence", 0.5),
                        "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                    })
                    # 只保留最近 20 条情感记录
                    profile_data["sentiment_history"] = history[-20:]

            # ── 常规统计 ──

            # 话题统计
            topics = profile_data.get("topic_stats", {})
            if intent:
                topics[intent] = topics.get(intent, 0) + 1
            profile_data["topic_stats"] = topics

            # 最近活跃时间（可能已被 profile_delta 设置）
            if not profile_data.get("last_active_at"):
                profile_data["last_active_at"] = time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.localtime()
                )

            # ── 保存 ──
            self.create_or_update_user(
                user_id=user_id,
                name=name,
                tags=tags,
                profile=profile_data,
            )
            self.logger.bind(tag=TAG).debug(
                f"用户画像已更新: user={user_id}, interests={profile_data.get('interests', [])}"
            )
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"从对话更新用户画像失败: {e}")

    # ------------------------------------------------------------------
    # 对话记录
    # ------------------------------------------------------------------

    def save_conversation(
        self,
        user_id: str,
        session_id: str,
        query: str,
        response: str,
        intent: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ):
        if not user_id:
            return
        try:
            with self._get_conn() as conn:
                conn.execute(
                    """INSERT INTO conversations (user_id, session_id, query, response, intent, metadata)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        session_id,
                        query,
                        response,
                        intent,
                        json.dumps(metadata or {}, ensure_ascii=False),
                    ),
                )
                conn.commit()
                self.logger.bind(tag=TAG).debug(
                    f"对话已保存: user={user_id}, session={session_id}"
                )
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"保存对话失败: {e}")

    def get_conversation_history(
        self, user_id: str, limit: int = 20
    ) -> List[Dict[str, Any]]:
        if not user_id:
            return []
        try:
            with self._get_conn() as conn:
                rows = conn.execute(
                    """SELECT * FROM conversations
                       WHERE user_id = ?
                       ORDER BY created_at DESC
                       LIMIT ?""",
                    (user_id, limit),
                ).fetchall()
            return [
                {
                    "id": row["id"],
                    "user_id": row["user_id"],
                    "session_id": row["session_id"],
                    "query": row["query"],
                    "response": row["response"],
                    "intent": row["intent"],
                    "created_at": row["created_at"],
                }
                for row in reversed(rows)  # 正序返回
            ]
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"查询对话历史失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_user_dict(row) -> Dict[str, Any]:
        """将 sqlite3.Row 转换为字典，解析 JSON 字段"""
        result = dict(row)
        for field in ("tags", "profile"):
            if isinstance(result.get(field), str):
                try:
                    result[field] = json.loads(result[field])
                except (json.JSONDecodeError, TypeError):
                    pass
        return result

    def close(self):
        """SQLite 连接由 context manager 自动管理，此处无需操作"""
        pass
