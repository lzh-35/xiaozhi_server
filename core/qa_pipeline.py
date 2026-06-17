"""
解耦后的语音问答核心管道 (Q&A Pipeline)

支持的对话模式（由 config.selected_module.Intent 控制）：
- nointent / function_call → LLM 原生 function calling
- 集成 Memory（会话记忆）、Tools（插件调用）
"""

import io
import json
import time
import wave
import uuid
import asyncio
import threading
from collections import Counter
from typing import Optional

from config.logger import setup_logging
from core.providers.asr.base import ASRProviderBase
from core.providers.llm.base import LLMProviderBase
from core.providers.tts.base import TTSProviderBase
from core.utils.dialogue import Message, Dialogue
from core.utils.tts import MarkdownCleaner
from core.tool_handler import PipelineContext, SimplifiedToolHandler
from plugins_func.register import Action, ActionResponse

TAG = __name__

class QAPipeline:
    """语音问答管道：ASR → LLM → TTS
    支持 Memory（会话记忆）、Tools（插件调用）
    """

    def __init__(
        self,
        asr: ASRProviderBase,
        llm: LLMProviderBase,
        tts: Optional[TTSProviderBase],
        config: dict,
        memory=None,
        intent_type: str = "nointent",
        session_id: str = "",
        client_ip: str = "",
        crm=None,
        user_id: str = "",
    ):
        self.asr = asr
        self.llm = llm
        self.tts = tts
        self.config = config
        self.memory = memory
        self.intent_type = intent_type
        self.session_id = session_id or str(uuid.uuid4().hex)
        self.client_ip = client_ip or "127.0.0.1"
        self.crm = crm
        self.user_id = user_id
        self.logger = setup_logging()

        # 对话上下文（多轮会话）
        self.dialogue = Dialogue()

        # 构建增强系统提示词（模板渲染 + 动态上下文）
        enhanced_prompt = self._build_system_prompt()
        if enhanced_prompt:
            self.dialogue.put(Message(role="system", content=enhanced_prompt))

        # 工具处理器（仅 function_call 模式初始化）
        self.tool_handler: Optional[SimplifiedToolHandler] = None
        if self.intent_type == "function_call":
            ctx = PipelineContext(
                config=config,
                session_id=self.session_id,
                dialogue=self.dialogue,
                logger=self.logger,
                client_ip=self.client_ip,
            )
            self.tool_handler = SimplifiedToolHandler(ctx)

        # 初始化记忆模块
        if self.memory is not None:
            self._init_memory()

    def _build_system_prompt(self) -> str:
        """使用 PromptManager 构建增强系统提示词，注入 CRM 用户画像，失败时回退到 raw prompt"""
        base_prompt = self.config.get("prompt", "")
        if not base_prompt:
            return ""
        try:
            from core.utils.prompt_manager import PromptManager
            pm = PromptManager(self.config, self.logger)
            prompt = pm.build_enhanced_prompt(
                user_prompt=base_prompt,
                device_id=self.session_id,
                client_ip=self.client_ip,
                emoji_enabled=True,
            )
        except Exception as e:
            self.logger.bind(tag=TAG).debug(f"增强提示词构建失败，使用原始提示词: {e}")
            prompt = base_prompt

        # 注入 CRM 用户画像
        user_profile_str = self._get_user_profile()
        if user_profile_str:
            prompt += user_profile_str

        return prompt

    def _get_user_profile(self) -> str:
        """查询 CRM 用户画像并格式化为 prompt 片段"""
        if not self.crm or not self.user_id:
            return ""
        try:
            profile = self.crm.get_user_profile(self.user_id)
            if not profile:
                return ""

            parts = ["\n\n<user_profile>"]
            if profile.get("name"):
                parts.append(f"- 姓名: {profile['name']}")
            tags = profile.get("tags", [])
            if tags:
                parts.append(f"- 标签: {', '.join(tags)}")

            profile_data = profile.get("profile", {})
            if isinstance(profile_data, str):
                try:
                    profile_data = json.loads(profile_data)
                except Exception:
                    profile_data = {}
            if profile_data:
                # 提取关键画像字段
                if "topic_stats" in profile_data:
                    topics = profile_data["topic_stats"]
                    if topics:
                        top_topics = sorted(topics.items(), key=lambda x: x[1], reverse=True)[:3]
                        parts.append(f"- 高频话题: {', '.join(f'{t}({c}次)' for t, c in top_topics)}")
                # 其他画像信息
                for key in ("preferences", "purchased", "concerns"):
                    if key in profile_data:
                        parts.append(f"- {key}: {profile_data[key]}")

            parts.append("</user_profile>")
            parts.append("请根据以上用户画像调整回复风格和内容，做到个性化服务。")
            return "\n".join(parts)
        except Exception as e:
            self.logger.bind(tag=TAG).debug(f"获取用户画像失败: {e}")
            return ""

    def _save_to_crm(self, query: str, response: str):
        """保存对话到 CRM 并更新用户画像（闭环）

        1. 确保用户存在（不存在则自动注册）
        2. 保存对话记录到 SQLite
        3. 调 LLM 从对话中提取用户关键信息（偏好、购买意向、关注话题等）
        4. 将提取的结构化信息更新到 CRM 用户画像
        """
        if not self.crm or not self.user_id:
            return
        try:
            # 确保用户存在（新用户自动注册）
            profile = self.crm.get_user_profile(self.user_id)
            if profile is None:
                self.crm.create_or_update_user(
                    user_id=self.user_id, phone=self.user_id
                )

            # 保存对话记录
            self.crm.save_conversation(
                user_id=self.user_id,
                session_id=self.session_id,
                query=query,
                response=response,
                intent=self.intent_type,
            )

            # LLM 提取用户画像 delta（后台线程，不阻塞）

            def _extract_and_update():
                try:
                    profile_delta = self._extract_profile_delta(query, response)
                    if profile_delta:
                        # 合并 topic_stats
                        topics = profile_delta.get("topic_stats", {})
                        topics[self.intent_type] = topics.get(self.intent_type, 0) + 1
                        profile_delta["topic_stats"] = topics
                        profile_delta["last_active_at"] = time.strftime(
                            "%Y-%m-%d %H:%M:%S", time.localtime()
                        )
                    self.crm.update_user_from_conversation(
                        user_id=self.user_id,
                        query=query,
                        response=response,
                        intent=self.intent_type,
                        profile_delta=profile_delta,
                    )
                except Exception as e:
                    self.logger.bind(tag=TAG).debug(f"LLM 画像提取失败: {e}")

            t = threading.Thread(target=_extract_and_update, daemon=True)
            t.start()
        except Exception as e:
            self.logger.bind(tag=TAG).debug(f"CRM 保存失败: {e}")

    # ── LLM 驱动的用户画像提取 ──

    USER_PROFILE_EXTRACTION_PROMPT = """你是一个用户画像分析师。请从以下对话中提取用户的关键信息，以 JSON 格式返回。

## 提取维度
1. **identity**: 用户身份信息
   - name: 用户姓名（如有提及）
   - role: 角色（如"宝妈""程序员""退休老人"等）
   - member_level: 会员等级（如有提及普通/银卡/金卡/钻石）

2. **interests**: 关注话题列表
   - 用户在本轮对话中表现出兴趣的话题
   - 例如: ["产品保修", "套餐升级", "节能优化"]

3. **intents**: 意图列表
   - 用户本轮的真实需求
   - 例如: ["查询保修期", "了解升级政策"]

4. **sentiment**: 情感倾向
   - positive / neutral / negative
   - 对应 confidence: 0.0-1.0

5. **facts**: 从对话中提取的事实信息
   - 键值对形式，例如: {"购买的套餐": "旗舰套餐", "购买时间": "2025年3月"}
   - 仅提取用户明确提到的信息，不要推测

## 输出格式（必须严格 JSON）
```json
{
  "identity": {"name": "", "role": "", "member_level": ""},
  "interests": [],
  "intents": [],
  "sentiment": {"polarity": "neutral", "confidence": 0.5},
  "facts": {}
}
```

## 规则
- 仅提取用户侧信息，不提取系统回复中的信息
- 字段为空时填 "" 或 [] 或 {}
- 不要编造任何信息
- 只输出 JSON，不要任何解释文字"""

    def _extract_profile_delta(self, query: str, response: str) -> dict:
        """调 LLM 从一轮对话中提取用户画像增量"""
        try:
            user_msg = f"用户: {query}\n助手: {response}"
            result = self.llm.response_no_stream(
                system_prompt=self.USER_PROFILE_EXTRACTION_PROMPT,
                user_prompt=user_msg,
                max_tokens=500,
                temperature=0.1,
            )
            # 从 LLM 回复中提取 JSON
            json_str = result
            start = json_str.find("{")
            end = json_str.rfind("}")
            if start != -1 and end != -1:
                json_str = json_str[start:end + 1]

            delta = json.loads(json_str)
            self.logger.bind(tag=TAG).debug(f"用户画像提取: {delta.get('interests', [])}")
            return delta
        except Exception as e:
            self.logger.bind(tag=TAG).debug(f"画像提取解析失败: {e}")
            return {}

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def ask_text(self, question: str) -> str:
        """文本问答：输入文本 → 返回文本（带记忆 & 工具调用）"""
        result = None
        for event in self.ask_text_stream(question):
            if event.get("done"):
                result = event.get("text", "")
        return result or ""

    def ask_text_stream(self, question: str):
        """文本问答流式版：逐 token yield，支持 SSE"""
        self.logger.bind(tag=TAG).info(f"文本问答: {question[:80]}...")

        # 1. 记忆检索
        memory_str = self._query_memory(question)

        # 2. 构建对话
        self.dialogue.put(Message(role="user", content=question))

        # 3. LLM 调用（function_call 模式支持工具调用）
        full_text = ""
        if self.intent_type == "function_call" and self.tool_handler is not None:
            for token in self._chat_with_tools_stream(memory_str):
                if isinstance(token, dict) and token.get("done"):
                    full_text = token.get("text", "")
                    yield token
                else:
                    yield {"token": token}
        else:
            for token in self._chat_simple_stream(memory_str):
                if isinstance(token, dict) and token.get("done"):
                    full_text = token.get("text", "")
                    yield token
                else:
                    yield {"token": token}

        # 4. 保存记忆
        self._save_memory()

        # 4.5 保存到 CRM（闭环：对话记录 + 更新用户画像）
        if full_text:
            self._save_to_crm(question, full_text)

        self.logger.bind(tag=TAG).info(f"LLM 回复: {full_text[:80]}...")

        # 5. 最终事件
        yield {
            "done": True,
            "text": full_text,
            "session_id": self.session_id,
        }

    async def ask_voice(
        self, audio_bytes: bytes, return_audio: bool = False
    ) -> dict:
        """语音问答：上传音频 → ASR → LLM → (可选 TTS)"""
        asr_text = await self._speech_to_text(audio_bytes, self.session_id)
        if not asr_text:
            return {"text": "", "asr_text": "", "audio": None}

        self.logger.bind(tag=TAG).info(f"ASR 识别: {asr_text[:80]}...")

        response_text = self.ask_text(asr_text)

        audio_output = None
        if return_audio and self.tts and response_text:
            audio_output = await self._text_to_speech(response_text)

        return {
            "text": response_text,
            "asr_text": asr_text,
            "audio": audio_output,
        }

    async def ask_voice_stream(self, audio_bytes: bytes):
        """语音问答流式版：ASR → LLM逐字 → TTS逐块音频

        SSE 事件格式:
          {"type": "asr", "text": "..."}       # ASR 识别完成
          {"type": "token", "data": "文"}       # LLM 逐字
          {"type": "text_done", "text": "..."} # LLM 完成
          {"type": "audio", "data": "<base64>"}# TTS 音频块
          {"type": "done", "session_id": "..."}# 结束
        """
        import base64

        # 1. ASR
        asr_text = await self._speech_to_text(audio_bytes, self.session_id)
        if not asr_text:
            yield {"type": "done", "error": "ASR 未识别到语音"}
            return
        yield {"type": "asr", "text": asr_text}

        # 2. LLM 流式（复用内部方法）
        self.logger.bind(tag=TAG).info(f"语音问答流式: {asr_text[:80]}...")
        self.dialogue.put(Message(role="user", content=asr_text))
        memory_str = self._query_memory(asr_text)

        full_text = ""
        if self.intent_type == "function_call" and self.tool_handler is not None:
            for token in self._chat_with_tools_stream(memory_str):
                if isinstance(token, dict) and token.get("done"):
                    full_text = token.get("text", "")
                else:
                    yield {"type": "token", "data": token}
        else:
            for token in self._chat_simple_stream(memory_str):
                if isinstance(token, dict) and token.get("done"):
                    full_text = token.get("text", "")
                else:
                    yield {"type": "token", "data": token}

        if not full_text:
            yield {"type": "done", "text": ""}
            return

        yield {"type": "text_done", "text": full_text}

        # 3. TTS 流式
        if self.tts and hasattr(self.tts, "text_to_speak_stream"):
            try:
                async for chunk in self.tts.text_to_speak_stream(full_text):
                    yield {"type": "audio", "data": base64.b64encode(chunk).decode("utf-8")}
            except Exception as e:
                self.logger.bind(tag=TAG).warning(f"TTS 流式失败: {e}")

        self._save_memory()
        if full_text:
            self._save_to_crm(asr_text, full_text)
        yield {"type": "done", "text": full_text, "session_id": self.session_id}

    # ------------------------------------------------------------------
    # LLM 调用（简单模式：无工具）
    # ------------------------------------------------------------------

    def _chat_simple(self, memory_str: Optional[str]) -> str:
        """简单的 LLM 对话，不涉及工具调用"""
        llm_dialogue = self._build_llm_dialogue(memory_str)
        parts = []
        for chunk in self.llm.response(self.session_id, llm_dialogue):
            content = self._extract_content(chunk)
            if content:
                parts.append(content)
        text = "".join(parts)
        self.dialogue.put(Message(role="assistant", content=text))
        return text

    def _chat_simple_stream(self, memory_str: Optional[str]):
        """简单 LLM 对话的流式版"""
        llm_dialogue = self._build_llm_dialogue(memory_str)
        full_text = ""
        for chunk in self.llm.response(self.session_id, llm_dialogue):
            content = self._extract_content(chunk)
            if content:
                full_text += content
                yield content
        self.dialogue.put(Message(role="assistant", content=full_text))
        yield {"done": True, "text": full_text}

    def _build_llm_dialogue(self, memory_str: Optional[str]) -> list:
        """构建 LLM 对话，注入记忆"""
        llm_dialogue = self.dialogue.get_llm_dialogue_with_memory(
            memory_str, self.config.get("voiceprint", {})
        )
        # 如果记忆不为空但注入失败（prompt 缺少 <memory> 标签），手动追加
        if memory_str and len(memory_str) > 0:
            has_memory = any(
                "<memory>" in str(msg.get("content", "")) for msg in llm_dialogue
            )
            if not has_memory:
                llm_dialogue.insert(
                    1,
                    {
                        "role": "system",
                        "content": f"<context>\n<memory>\n{memory_str}\n</memory>\n</context>",
                    },
                )
        return llm_dialogue

    # ------------------------------------------------------------------
    # LLM 调用（function_call 模式：带工具）
    # ------------------------------------------------------------------

    def _chat_with_tools(self, memory_str: Optional[str], depth: int = 0) -> str:
        """LLM 对话 + 原生 function calling"""
        MAX_DEPTH = 5
        if depth >= MAX_DEPTH:
            # 强制最终回复
            self.dialogue.put(
                Message(
                    role="user",
                    content="[系统提示] 已达到最大工具调用次数，请基于已有信息直接回复。",
                )
            )
            return self._chat_simple(memory_str)

        # 构建 LLM 请求
        llm_dialogue = self._build_llm_dialogue(memory_str)
        functions = list(self.tool_handler.get_functions())

        # 流式调用
        content_parts = []
        tool_calls_list = []
        try:
            for chunk in self.llm.response_with_functions(
                self.session_id, llm_dialogue, functions=functions
            ):
                content, tools_call = self._parse_chunk(chunk)
                if content:
                    content_parts.append(content)
                if tools_call:
                    self._merge_tool_calls(tool_calls_list, tools_call)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 调用失败: {e}")
            fallback = self.config.get("system_error_response", "抱歉，出了点问题。")
            self.dialogue.put(Message(role="assistant", content=fallback))
            return fallback

        # 如果没有工具调用，直接返回
        if not tool_calls_list:
            text = "".join(content_parts)
            self.dialogue.put(Message(role="assistant", content=text))
            return text

        # 处理工具调用
        return self._handle_tool_calls(tool_calls_list, depth)

    def _handle_tool_calls(self, tool_calls_list: list, depth: int) -> str:
        """执行工具调用并递归"""
        # 写入 assistant(tool_calls) 消息
        tool_call_msgs = [
            {
                "id": tc.get("id", str(uuid.uuid4().hex)),
                "function": {
                    "name": tc["name"],
                    "arguments": tc.get("arguments", "{}"),
                },
                "type": "function",
                "index": i,
            }
            for i, tc in enumerate(tool_calls_list)
        ]
        self.dialogue.put(Message(role="assistant", tool_calls=tool_call_msgs))

        # 执行工具
        need_llm = False
        for tc in tool_calls_list:
            try:
                try:
                    loop = asyncio.get_running_loop()
                    future = asyncio.run_coroutine_threadsafe(
                        self.tool_handler.handle_llm_function_call(tc), loop
                    )
                    result = future.result(timeout=30)
                except RuntimeError:
                    result = asyncio.run(
                        self.tool_handler.handle_llm_function_call(tc)
                    )
            except Exception as e:
                result = ActionResponse(action=Action.ERROR, response=str(e))

            if result is None:
                continue

            self.dialogue.put(
                Message(
                    role="tool",
                    tool_call_id=tc.get("id", str(uuid.uuid4().hex)),
                    content=result.result or result.response or "",
                )
            )

            if result.action == Action.RESPONSE:
                self.dialogue.put(
                    Message(role="assistant", content=result.response or result.result)
                )
            elif result.action == Action.REQLLM:
                need_llm = True
            elif result.action == Action.RECORD:
                self.dialogue.put(
                    Message(role="assistant", content=result.response or result.result)
                )

        if need_llm:
            return self._chat_with_tools(None, depth + 1)

        return result.result or result.response or ""

    def _chat_with_tools_stream(self, memory_str: Optional[str], depth: int = 0):
        """带工具调用的流式 LLM 对话 — 先判断工具，再流式输出最终回复"""
        MAX_DEPTH = 5
        if depth >= MAX_DEPTH:
            self.dialogue.put(
                Message(
                    role="user",
                    content="[系统提示] 已达到最大工具调用次数，请基于已有信息直接回复。",
                )
            )
            yield from self._chat_simple_stream(memory_str)
            return

        llm_dialogue = self._build_llm_dialogue(memory_str)
        functions = list(self.tool_handler.get_functions()) if self.tool_handler else []

        # 收集完整响应（先不做流式，因为可能有工具调用）
        content_parts = []
        tool_calls_list = []
        try:
            for chunk in self.llm.response_with_functions(
                self.session_id, llm_dialogue, functions=functions
            ):
                content, tools_call = self._parse_chunk(chunk)
                if content:
                    content_parts.append(content)
                if tools_call:
                    self._merge_tool_calls(tool_calls_list, tools_call)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"LLM 调用失败: {e}")
            fallback = self.config.get("system_error_response", "抱歉，出了点问题。")
            self.dialogue.put(Message(role="assistant", content=fallback))
            yield fallback
            yield {"done": True, "text": fallback}
            return

        # 没有工具调用 → 流式输出已收集内容
        if not tool_calls_list:
            text = "".join(content_parts)
            self.dialogue.put(Message(role="assistant", content=text))
            # 模拟流式：逐字输出
            for char in text:
                yield char
            yield {"done": True, "text": text}
            return

        # 有工具调用 → 执行 → 递归
        text = self._handle_tool_calls(tool_calls_list, depth)
        # 递归后的结果可能是流式的，逐字输出
        for char in text:
            yield char
        yield {"done": True, "text": text}

    # ------------------------------------------------------------------
    # Memory 集成
    # ------------------------------------------------------------------

    def _init_memory(self):
        """初始化记忆模块 — 优先使用 user_id 作为记忆 key，跨会话保持"""
        try:
            # 有 user_id 时用 user_id 做记忆 key（跨会话持久化）
            # 没有 user_id 时回退到 session_id（每次新会话空白记忆）
            memory_role_id = self.user_id if self.user_id else self.session_id
            self.memory.init_memory(
                role_id=memory_role_id,
                llm=self.llm,
                summary_memory=self.config.get("summaryMemory", None),
                save_to_file=True,
            )
            self.logger.bind(tag=TAG).info(
                f"记忆模块初始化成功 (key={memory_role_id})"
            )
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"记忆模块初始化失败: {e}")
            self.memory = None

    def _query_memory(self, query: str) -> Optional[str]:
        """查询相关记忆"""
        if self.memory is None or not query:
            return None
        try:
            # mem_local_short 直接读缓存，不需要异步
            cached = getattr(self.memory, "short_memory", "")
            if cached and len(cached) > 0:
                return f"用户历史记忆：\n{cached}"
            return None
        except Exception as e:
            self.logger.bind(tag=TAG).debug(f"记忆查询跳过: {e}")
            return None

    def _save_memory(self):
        """保存对话到记忆（独立线程，不阻塞主流程）"""
        if self.memory is None:
            return
        try:
            memory = self.memory
            dialogue = list(self.dialogue.dialogue)
            session_id = self.session_id

            logger = self.logger

            def _save():
                try:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    loop.run_until_complete(
                        memory.save_memory(dialogue, session_id)
                    )
                except Exception as e:
                    logger.bind(tag=TAG).debug(f"后台记忆保存失败: {e}")
                finally:
                    try:
                        loop.close()
                    except Exception as e:
                        logger.bind(tag=TAG).debug(f"关闭事件循环失败: {e}")

            t = threading.Thread(target=_save, daemon=True)
            t.start()
            self.logger.bind(tag=TAG).debug("记忆保存已提交（后台线程）")
        except Exception as e:
            self.logger.bind(tag=TAG).warning(f"记忆保存提交失败: {e}")

    # ------------------------------------------------------------------
    # VLLM 视觉问答（接入管道，享受 Memory）
    # ------------------------------------------------------------------

    def ask_vision(self, image_base64: str, question: str) -> str:
        """图片问答：VLLM 分析 + 记忆保存"""
        from core.utils.vllm import create_instance as create_vllm

        vllm_name = self.config["selected_module"].get("VLLM", "")
        if not vllm_name:
            return "VLLM 未配置"

        vllm_type = self.config["VLLM"][vllm_name].get("type", "openai")
        vllm = create_vllm(vllm_type, self.config["VLLM"][vllm_name])
        text = vllm.response(question, image_base64)

        # 写入对话 + 记忆
        self.dialogue.put(Message(role="user", content=f"[图片] {question}"))
        self.dialogue.put(Message(role="assistant", content=text))
        self._save_memory()
        if text:
            self._save_to_crm(f"[图片] {question}", text)

        return text

    # ------------------------------------------------------------------
    # ASR / TTS（不变）
    # ------------------------------------------------------------------

    # ASR PCM 分帧: 60ms * 16kHz * 2bytes = 1920
    _ASR_FRAME_SIZE = 1920

    async def _speech_to_text(self, audio_bytes: bytes, session_id: str) -> str:
        try:
            pcm_data = _wav_to_pcm_bytes(audio_bytes)
            if not pcm_data:
                return ""
            frames = [
                pcm_data[i : i + QAPipeline._ASR_FRAME_SIZE]
                for i in range(0, len(pcm_data), QAPipeline._ASR_FRAME_SIZE)
            ]
            if not frames:
                return ""
            result = await self.asr.speech_to_text_wrapper(
                frames, session_id, audio_format="pcm"
            )
            text, _ = result if isinstance(result, tuple) else (result, None)
            if isinstance(text, dict):
                return text.get("content", "") or ""
            return text or ""
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"ASR 失败: {e}")
            return ""

    async def _text_to_speech(self, text: str) -> Optional[bytes]:
        try:
            cleaned = MarkdownCleaner.clean_markdown(text)
            if not cleaned:
                return None
            return await self.tts.text_to_speak(cleaned, None)
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"TTS 失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 工具函数
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_content(chunk) -> Optional[str]:
        if chunk is None:
            return None
        if isinstance(chunk, str):
            return chunk
        if isinstance(chunk, tuple):
            content, _ = chunk
            return content if content else None
        if isinstance(chunk, dict):
            return chunk.get("content")
        return str(chunk)

    @staticmethod
    def _parse_chunk(chunk):
        """解析 LLM 流式响应块 → (content, tool_calls)"""
        if isinstance(chunk, tuple):
            return chunk
        if isinstance(chunk, dict):
            return chunk.get("content"), chunk.get("tool_calls")
        return chunk, None

    @staticmethod
    def _merge_tool_calls(tool_calls_list: list, tools_call):
        """合并流式 tool call delta"""
        for tc in tools_call:
            idx = getattr(tc, "index", None)
            if idx is None:
                idx = len(tool_calls_list) - 1 if tool_calls_list else 0
            while idx >= len(tool_calls_list):
                tool_calls_list.append({"id": "", "name": "", "arguments": ""})
            if tc.id:
                tool_calls_list[idx]["id"] = tc.id
            if tc.function.name:
                tool_calls_list[idx]["name"] = tc.function.name
            if tc.function.arguments:
                tool_calls_list[idx]["arguments"] += tc.function.arguments

    async def close(self):
        if self.asr and hasattr(self.asr, "close"):
            await self.asr.close()
        if self.tts and hasattr(self.tts, "close"):
            await self.tts.close()


def _wav_to_pcm_bytes(data: bytes) -> Optional[bytes]:
    try:
        with wave.open(io.BytesIO(data), "rb") as wf:
            if wf.getnchannels() not in (1, 2):
                return None
            return wf.readframes(wf.getnframes())
    except Exception:
        return None
