"""日志配置 — 基于 loguru"""

import os
import sys
from loguru import logger
from config.config_loader import load_config

SERVER_VERSION = "0.1.0"
_logger_initialized = False


def _formatter(record):
    """为日志记录添加默认 tag 和模块字符串"""
    record["extra"].setdefault("tag", record["name"])
    record["extra"].setdefault("selected_module", "00000000000000")
    record["selected_module"] = record["extra"]["selected_module"]
    return record["message"]


def setup_logging():
    """从配置文件读取日志配置，设置输出格式和级别"""
    config = load_config()
    log_config = config["log"]
    global _logger_initialized

    if not _logger_initialized:
        logger.configure(
            extra={
                "selected_module": log_config.get("selected_module", "00000000000000"),
            }
        )

        log_format = log_config.get(
            "log_format",
            "<green>{time:YYMMDD HH:mm:ss}</green>[{version}_{extra[selected_module]}]"
            "[<light-blue>{extra[tag]}</light-blue>]-<level>{level}</level>"
            "-<light-green>{message}</light-green>",
        )
        log_format_file = log_config.get(
            "log_format_file",
            "{time:YYYY-MM-DD HH:mm:ss} - {version}_{extra[selected_module]} - "
            "{name} - {level} - {extra[tag]} - {message}",
        )
        log_format = log_format.replace("{version}", SERVER_VERSION)
        log_format_file = log_format_file.replace("{version}", SERVER_VERSION)

        log_level = log_config.get("log_level", "INFO")
        log_dir = log_config.get("log_dir", "tmp")
        log_file = log_config.get("log_file", "server.log")
        data_dir = log_config.get("data_dir", "data")

        os.makedirs(log_dir, exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)

        logger.remove()
        logger.add(sys.stdout, format=log_format, level=log_level, filter=_formatter)
        logger.add(
            os.path.join(log_dir, log_file),
            format=log_format_file,
            level=log_level,
            filter=_formatter,
            rotation="10 MB",
            retention="30 days",
            encoding="utf-8",
            enqueue=True,
            backtrace=True,
            diagnose=True,
        )
        _logger_initialized = True

    return logger
