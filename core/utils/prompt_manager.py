"""
系统提示词管理器 — REST API 精简版
负责：加载模板 + 注入时间/日期/农历 + Jinja2 渲染
"""

import os
from typing import Dict, Any
from config.logger import setup_logging

TAG = __name__

EMOJI_List = [
    "😶", "🙂", "😆", "😂", "😔", "😠", "😭", "😍",
    "😳", "😲", "😱", "🤔", "😉", "😎", "😌", "🤤",
    "😘", "😏", "😴", "😜", "🙄",
]


class PromptManager:
    """系统提示词管理器"""

    def __init__(self, config: Dict[str, Any], logger=None):
        self.config = config
        self.logger = logger or setup_logging()
        self.base_prompt_template = None
        self._load_base_template()

    def _load_base_template(self):
        """加载基础提示词模板文件"""
        try:
            template_path = self.config.get("prompt_template", "agent-base-prompt.txt")
            if os.path.exists(template_path):
                with open(template_path, "r", encoding="utf-8") as f:
                    self.base_prompt_template = f.read()
                self.logger.bind(tag=TAG).debug(f"已加载提示词模板: {template_path}")
            else:
                self.logger.bind(tag=TAG).warning(f"未找到模板文件: {template_path}")
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"加载提示词模板失败: {e}")

    def _get_current_time_info(self) -> tuple:
        """获取当前时间 / 日期 / 农历"""
        from .current_time import (
            get_current_date,
            get_current_weekday,
            get_current_lunar_date,
        )
        return get_current_date(), get_current_weekday(), get_current_lunar_date() + "\n"

    def build_enhanced_prompt(self, user_prompt: str, **kwargs) -> str:
        """构建增强系统提示词：模板渲染 + 动态信息注入"""
        if not self.base_prompt_template:
            return user_prompt

        try:
            from jinja2 import Template

            today_date, today_weekday, lunar_date = self._get_current_time_info()
            language = (
                self.config.get("TTS", {})
                .get(self.config.get("selected_module", {}).get("TTS", ""), {})
                .get("language") or "中文"
            )

            template = Template(self.base_prompt_template)
            enhanced = template.render(
                base_prompt=user_prompt,
                current_time="{{current_time}}",
                today_date=today_date,
                today_weekday=today_weekday,
                lunar_date=lunar_date,
                emojiList=EMOJI_List,
                language=language,
                emoji_enabled=kwargs.get("emoji_enabled", True),
            )
            self.logger.bind(tag=TAG).info(f"构建增强提示词成功，长度: {len(enhanced)}")
            return enhanced
        except Exception as e:
            self.logger.bind(tag=TAG).error(f"构建增强提示词失败: {e}")
            return user_prompt
