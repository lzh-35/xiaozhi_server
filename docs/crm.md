# AICRM 集成说明文档

## 概述

XiaoZhi 语音问答系统已集成 **AICRM（AI 客户关系管理）** 模块，包含两个核心能力：

| 模块 | 功能 | 技术栈 |
|------|------|--------|
| **CRM** | 用户画像管理、对话记录、个性化回复 | SQLite |
| **RAG** | 知识库检索、产品手册/FAQ/政策问答 | LangChain + Chroma + DashScope text-embedding-v4 |

---

## 架构

```
用户输入（文本/语音/图片）
        │
        ├──→ 分支A: 意图路由（LLM Function Calling）
        │         ├── 实时资讯 → web_search / get_weather / get_news
        │         ├── 知识库类 → search_knowledge_base（RAG 检索）
        │         └── 闲聊通用 → LLM 直接回答
        │
        └──→ 分支B: CRM 用户画像
                  ├── 查用户画像 → 注入 system prompt
                  ├── 个性化回复 → LLM 结合画像生成
                  └── 闭环更新 → 对话后更新用户画像
```

### 完整调用链路示例

```
1. 用户语音: "我的旗舰套餐保修到什么时候？"
2. ASR → text
3. CRM 查用户画像: {name: "张三", purchased: [{product: "旗舰套餐", date: "2025-03-15"}]}
4. 注入画像到 system prompt
5. LLM 判断意图: 知识库类 → 调用 search_knowledge_base("旗舰套餐 保修期")
6. RAG 从产品手册检索: "旗舰套餐保修期2年"
7. LLM 综合画像+检索结果: "张三先生，您2025年3月15日购买的旗舰套餐保修到2027年3月15日哦~"
8. CRM 保存对话 + 更新用户画像闭环
```

---

## API 端点

### 问答接口（已有，新增 user_id 参数）

| 方法 | 路径 | 新增参数 |
|------|------|---------|
| POST | `/ask/text` | `user_id: str = ""` |
| POST | `/ask/voice` | `user_id: str = ""` |
| POST | `/ask/voice/stream` | `user_id: str = ""` |
| POST | `/ask/vision` | `user_id: str = ""` |

不传 `user_id` 时行为不变，向后兼容。

### CRM 管理接口（新增）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/crm/users/{user_id}` | 查询用户完整档案（画像 + 对话历史） |
| POST | `/crm/users` | 创建/更新用户 |
| GET | `/crm/users/{user_id}/conversations` | 查询用户对话历史 |
| GET | `/crm/health` | CRM 模块健康检查 |
| GET | `/crm/knowledge` | 查看知识库索引状态 |
| POST | `/crm/knowledge/reload` | 强制重建知识库索引 |

---

## 配置说明

在 `data/.config.yaml` 中配置：

```yaml
# 模块选择
selected_module:
  CRM: crm_sqlite           # CRM Provider（留空=禁用）

# CRM 配置
CRM:
  crm_sqlite:
    type: crm_sqlite

crm:
  db_path: "data/crm.db"

# RAG 配置
rag:
  embedding_model: text-embedding-v4
  dashscope_api_key: "sk-xxx"           # 阿里 DashScope API Key
  knowledge_dir: "data/knowledge_base"  # 知识库文档目录
  persist_dir: "data/chroma_db"         # 向量库目录
  chunk_size: 500
  chunk_overlap: 50
  top_k: 3

# 意图配置（需添加 search_knowledge_base）
Intent:
  function_call:
    type: function_call
    functions:
      - web_search
      - get_weather
      - get_news_from_newsnow
      - get_lunar
      - search_knowledge_base      # ← 新增 RAG 工具
```

---

## 知识库文档

知识库文档放在 `data/knowledge_base/` 目录下，支持 `.txt` 和 `.md` 格式。

当前示例文档：

| 文件 | 内容 |
|------|------|
| `产品手册.txt` | 智能家居产品线、套餐规格、保修政策、安装问题 |
| `FAQ常见问题.txt` | 订单、产品使用、套餐升级、联系客服 |
| `公司政策.txt` | 服务承诺、会员体系、隐私安全、投诉建议 |

### 添加新文档

1. 在 `data/knowledge_base/` 下添加 `.txt` 或 `.md` 文件
2. 调用 `POST /crm/knowledge/reload` 重建索引
3. 或者重启服务（启动时自动检测并重建）

---

## 数据库结构

### users 表

| 字段 | 类型 | 说明 |
|------|------|------|
| user_id | TEXT PK | 用户标识（手机号或自定义ID） |
| name | TEXT | 用户姓名 |
| phone | TEXT | 手机号 |
| tags | TEXT(JSON) | 标签数组，如 ["VIP客户"] |
| profile | TEXT(JSON) | 画像数据（话题统计、偏好等） |
| created_at | TEXT | 创建时间 |
| updated_at | TEXT | 更新时间 |

### conversations 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增ID |
| user_id | TEXT FK | 用户标识 |
| session_id | TEXT | 会话ID |
| query | TEXT | 用户问题 |
| response | TEXT | 系统回复 |
| intent | TEXT | 意图类型 |
| metadata | TEXT(JSON) | 附加元数据 |
| created_at | TEXT | 记录时间 |

---

## 测试方法

### 1. 测试 CRM 用户管理

```bash
# 创建用户
curl -X POST http://localhost:8080/crm/users \
  -H "Content-Type: application/json" \
  -d '{"user_id": "13800001111", "name": "张三", "tags": ["VIP客户"]}'

# 查询用户档案
curl http://localhost:8080/crm/users/13800001111
```

### 2. 测试带用户画像的问答

```bash
# 文本问答（带 user_id）
curl -X POST http://localhost:8080/ask/text \
  -H "Content-Type: application/json" \
  -d '{"text": "我的旗舰套餐保修多久？", "user_id": "13800001111", "stream": false}'
```

### 3. 测试 RAG 知识库检索

```bash
# 问一个知识库可以回答的问题
curl -X POST http://localhost:8080/ask/text \
  -H "Content-Type: application/json" \
  -d '{"text": "智能插座最大功率是多少？", "stream": false}'
```

### 4. 测试语音 + CRM

```bash
curl -X POST http://localhost:8080/ask/voice \
  -F "audio=@test.wav" \
  -F "user_id=13800001111" \
  -F "voice_output=false"
```

### 5. 查看知识库状态

```bash
curl http://localhost:8080/crm/knowledge
```

---

## 依赖安装

```bash
pip install -r requirements.txt
```

新增的 LangChain / RAG 相关依赖：
- `langchain` + `langchain-community` — LangChain 框架
- `langchain-chroma` — Chroma 向量库集成
- `langchain-text-splitters` — 文本分块
- `chromadb` — 向量数据库
- `dashscope` — 阿里 DashScope SDK（text-embedding-v4）

---

## 边界测试

| 场景 | 预期行为 |
|------|---------|
| 正常语音输入 | ASR → 意图识别 → 工具调用 → 个性化回复 |
| 无音源输入 / 空文件 | 返回 `code=1, message="ASR 未能识别"` |
| 知识库无匹配 | RAG 返回"未找到相关信息"，LLM 据实回复 |
| 不传 user_id | 无画像模式，正常对话（向后兼容） |
| 新用户首次对话 | 自动创建 CRM 用户记录 |
| 知识库文档变更 | 启动时自动重建索引，或手动 `/crm/knowledge/reload` |
| CRM 未配置 | 服务正常运行，仅 CRM 功能不可用 |
