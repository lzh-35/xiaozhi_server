# AICRM 客户管理系统 — 说明文档

## 一、系统概述

AICRM（AI Customer Relationship Management）是本项目的用户画像与对话管理子系统，与语音问答管道深度集成。用户在对话过程中，系统自动：

1. **记录对话** — 每轮对话存入 SQLite
2. **提取画像** — LLM 从对话中提取用户身份、兴趣、意图、情感
3. **个性化回复** — 下次对话时注入用户画像，实现千人千面

---

## 二、系统架构

```
┌─────────────────────────────────────────────────────┐
│                    用户交互层                          │
│   POST /ask/text    POST /ask/voice    POST /ask/vision │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                  QAPipeline (qa_pipeline.py)           │
│                                                       │
│  _get_user_profile()  ← 查询 CRM 画像，注入 prompt      │
│  _save_to_crm()       ← 保存对话 + 更新画像（闭环）       │
│  _extract_profile_delta() ← LLM 提取结构化画像增量       │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│                CRMProviderBase (抽象基类)               │
│                                                       │
│  get_user_profile()          查询用户画像              │
│  create_or_update_user()     创建/更新用户             │
│  update_user_from_conversation()  对话→画像闭环         │
│  save_conversation()         保存对话记录              │
│  get_conversation_history()  查询对话历史              │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────┐
│            CRMProvider (SQLite 实现)                   │
│                                                       │
│  data/crm.db  ← SQLite 数据库                         │
│  ├── users 表          (用户画像)                      │
│  └── conversations 表  (对话记录)                      │
└─────────────────────────────────────────────────────┘
```

---

## 三、数据库设计

### users 表（用户画像）

| 字段 | 类型 | 说明 |
|------|------|------|
| `user_id` | TEXT PRIMARY KEY | 用户标识（手机号/自定义 ID） |
| `name` | TEXT | 用户姓名 |
| `phone` | TEXT | 手机号 |
| `tags` | TEXT (JSON) | 用户标签，如 `["VIP", "科技爱好者"]` |
| `profile` | TEXT (JSON) | 用户画像 JSON，LLM 自动提取 |
| `created_at` | TEXT | 创建时间 |
| `updated_at` | TEXT | 更新时间 |

### conversations 表（对话记录）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK | 自增主键 |
| `user_id` | TEXT FK | 用户标识 |
| `session_id` | TEXT | 会话 ID |
| `query` | TEXT | 用户问题 |
| `response` | TEXT | 系统回复 |
| `intent` | TEXT | 意图分类 |
| `metadata` | TEXT (JSON) | 扩展信息 |
| `created_at` | TEXT | 创建时间 |

### profile JSON 结构（用户画像）

```json
{
  "interests": ["产品保修", "设备维护"],
  "last_intents": ["查询扫地机器人保修期"],
  "topic_stats": {"function_call": 5},
  "sentiment_history": [
    {"polarity": "positive", "confidence": 0.8, "time": "2026-06-17 12:00:00"}
  ],
  "facts": {"购买的套餐": "旗舰版", "购买时间": "2025年3月"},
  "last_active_at": "2026-06-17 15:30:00"
}
```

---

## 四、LLM 画像提取

### 提取流程

```
用户对话 → QAPipeline._save_to_crm()
  ├── 1. 保存对话记录到 conversations 表
  └── 2. 后台线程调用 LLM 提取画像
        ├── 发送对话给 LLM（USER_PROFILE_EXTRACTION_PROMPT）
        ├── LLM 返回结构化 JSON
        │   {
        │     "identity": {"name": "张三", "role": "", "member_level": "VIP"},
        │     "interests": ["产品保修"],
        │     "intents": ["查询保修政策"],
        │     "sentiment": {"polarity": "positive", "confidence": 0.8},
        │     "facts": {"购买套餐": "旗舰版"}
        │   }
        └── CRM.update_user_from_conversation() 增量合并到 profile
```

### 提取维度

| 维度 | 说明 |
|------|------|
| identity | 用户身份：姓名、角色、会员等级 |
| interests | 关注话题列表 |
| intents | 本轮真实需求 |
| sentiment | 情感倾向（positive/neutral/negative）+ 置信度 |
| facts | 从对话中提取的事实信息（键值对） |

### 增量合并策略

- **facts**: 合并到已有 facts，新值覆盖旧值
- **interests**: 去重追加
- **sentiment**: 追加到情感历史，保留最近 20 条
- **topic_stats**: 累加话题频次
- **tags**: 会员等级自动转为标签

---

## 五、REST API

### CRM 接口一览

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/crm/health` | CRM 健康检查 |
| `POST` | `/crm/users` | 创建/更新用户 |
| `GET` | `/crm/users/{user_id}` | 查询用户完整档案（画像+对话历史） |
| `GET` | `/crm/users/{user_id}/conversations` | 查询用户对话历史 |
| `GET` | `/crm/knowledge` | RAG 知识库状态 |
| `POST` | `/crm/knowledge/reload` | 重建知识库索引 |

### 接口详情

#### 创建/更新用户 `POST /crm/users`

```bash
curl -X POST http://localhost:8080/crm/users \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "13800138000",
    "name": "张三",
    "phone": "13800138000",
    "tags": ["VIP", "科技爱好者"],
    "profile": {"preferences": "扫地机器人"}
  }'
```

响应：
```json
{
  "user_id": "13800138000",
  "name": "张三",
  "phone": "13800138000",
  "tags": ["VIP", "科技爱好者"],
  "profile": {"preferences": "扫地机器人"},
  "created_at": "2026-06-17 12:00:00",
  "updated_at": "2026-06-17 12:00:00"
}
```

#### 查询用户档案 `GET /crm/users/{user_id}`

响应包含用户画像和最近 20 条对话记录。

#### 查询对话历史 `GET /crm/users/{user_id}/conversations?limit=20`

返回对话列表（正序），每项包含 query、response、intent、时间戳。

---

## 六、对话闭环流程

完整的一次语音 CRM 对话：

```
1. 客户端上传音频 + user_id + session_id
        │
2. POST /ask/voice
        │
3. QAPipeline:
   ├── ASR 语音识别
   ├── _get_user_profile() → 查询 CRM 画像 → 注入 prompt
   ├── LLM 回复（带个性化）
   ├── _save_to_crm(): 保存对话记录
   └── 后台线程: LLM 提取画像 → 更新 profile
        │
4. 下次请求:
   └── _get_user_profile() → 画像已更新 → LLM 知道用户是谁
```

### 代码调用链

```python
# qa_pipeline.py

def ask_text_stream(self, question):
    # ... LLM 回复 ...
    self._save_memory()
    self._save_to_crm(question, full_text)  # ← 闭环入口

def _save_to_crm(self, query, response):
    # 1. 确保用户存在
    # 2. 保存对话记录
    self.crm.save_conversation(user_id, session_id, query, response, intent)

    # 3. 后台线程：LLM 提取画像
    t = threading.Thread(target=_extract_and_update, daemon=True)
    t.start()

def _get_user_profile(self):
    # 查询 CRM 画像并格式化为 prompt 片段
    profile = self.crm.get_user_profile(self.user_id)
    return "<user_profile>姓名: 张三\n标签: VIP\n高频话题: ...</user_profile>"
```

---

## 七、配置说明

在 `data/.config.yaml` 中启用 CRM：

```yaml
selected_module:
  CRM: crm_sqlite

crm:
  db_path: "data/crm.db"
```

---

## 八、技术特点

| 特性 | 实现 |
|------|------|
| 存储引擎 | SQLite（零配置，嵌入式） |
| 并发安全 | WAL 模式 + 连接池 |
| 画像提取 | LLM 驱动（DeepSeek/GLM），后台异步 |
| 闭环更新 | 对话结束→自动提取→增量合并 |
| 个性化注入 | 下次对话时将画像片段拼入 system prompt |
| 可扩展 | Provider 模式，可实现 MySQL/PostgreSQL 等 |
