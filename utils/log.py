import sys
import re
from pathlib import Path
from loguru import logger

from conf import BASE_DIR


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def log_formatter(record: dict) -> str:
    """
    Formatter for log records.
    :param dict record: Log object containing log metadata & message.
    :returns: str
    """
    record["message"] = re.sub(r"[\U00010000-\U0010ffff\u2600-\u27bf]", "", str(record["message"])).strip()
    return "{time:YYYY-MM-DD HH:mm:ss} | {level} : {message}\n"


def create_logger(log_name: str, file_path: str):
    """
    Create custom logger for different business modules.
    :param str log_name: name of log
    :param str file_path: Optional path to log file
    :returns: Configured logger
    """
    def filter_record(record):
        return record["extra"].get("business_name") == log_name

    Path(BASE_DIR / file_path).parent.mkdir(exist_ok=True)
    logger.add(Path(BASE_DIR / file_path), filter=filter_record, level="INFO", rotation="10 MB", retention="10 days", backtrace=True, diagnose=True, encoding="utf-8")
    return logger.bind(business_name=log_name)


# Remove all existing handlers
logger.remove()
# Add a standard console handler
logger.add(sys.stdout, colorize=False, format=log_formatter)

douyin_logger = create_logger('douyin', 'logs/douyin.log')
tencent_logger = create_logger('tencent', 'logs/tencent.log')
xhs_logger = create_logger('xhs', 'logs/xhs.log')
tiktok_logger = create_logger('tiktok', 'logs/tiktok.log')
bilibili_logger = create_logger('bilibili', 'logs/bilibili.log')
kuaishou_logger = create_logger('kuaishou', 'logs/kuaishou.log')
baijiahao_logger = create_logger('baijiahao', 'logs/baijiahao.log')
xiaohongshu_logger = create_logger('xiaohongshu', 'logs/xiaohongshu.log')
