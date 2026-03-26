"""
配置管理模块。

推荐用法：
- OPENAI_API_KEY / OPENAI_BASE_URL 全局共享
- ANALYSIS_OPENAI_MODEL / SUMMARY_OPENAI_MODEL 按任务切模型
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
REPO_ROOT = Path(__file__).resolve().parents[1]
AI_CONFIG_PATH = REPO_ROOT / "ai_config.json"


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str | None
    base_url: str
    model: str


def load_user_dynamic_config() -> dict:
    """从仓库根目录加载可选的 ai_config.json。"""
    if not AI_CONFIG_PATH.exists():
        return {}

    try:
        with AI_CONFIG_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            return data
        logger.warning("ai_config.json is not a JSON object, ignoring it")
    except Exception as exc:
        logger.warning(f"Failed to load ai_config.json: {exc}")
    return {}


USER_DYNAMIC_CONFIG = load_user_dynamic_config()


PROJ_CONFIG = {
    "input_file": "unread_news.json",
    "limit": 100,
    "mark_read": False,
    "debug": False,
    "refresh": True,
    "proxy": "127.0.0.1:7890",
    "batch_scoring": True,
    "batch_size": 10,
    "max_workers": 3,
    "enable_vector_store": True,
    "scoring_persona": """
你是一名关注广泛的资深程序员。
你的核心身份是：
1. **技术专家**：关注测试开发、DevOps、AI 编程、Vibe Coding 等前沿技术。

除了技术，你还有两个重要的兴趣领域：
2. **投资理财 (P1)**：对市场动态、宏观经济、投资策略非常敏感。
3. **国际政治 (P2)**：关注地缘政治、国际关系等大局势新闻。

打分时，请根据**这三个维度的综合价值**来评估。如果文章主要讲技术，按技术标准评；如果讲投资或政治，按其深度和价值评。
""",
    "filter_keywords": ["推广", "广告", "特惠", "中奖", "开奖", "通知", "招聘"],
    "filter_min_length": 200,
    "filter_url_patterns": ["36kr.com/newsflashes/"],
    "scoring_weights": {
        "news": {
            "relevance": 0.40,
            "informativeness_accuracy": 0.35,
            "depth_opinion": 0.05,
            "readability": 0.15,
            "non_redundancy": 0.05,
        },
        "tutorial": {
            "relevance": 0.35,
            "informativeness_accuracy": 0.25,
            "depth_opinion": 0.10,
            "readability": 0.20,
            "non_redundancy": 0.10,
        },
        "opinion": {
            "relevance": 0.30,
            "informativeness_accuracy": 0.20,
            "depth_opinion": 0.35,
            "readability": 0.10,
            "non_redundancy": 0.05,
        },
        "default": {
            "relevance": 0.35,
            "informativeness_accuracy": 0.25,
            "depth_opinion": 0.20,
            "readability": 0.15,
            "non_redundancy": 0.05,
        },
    },
    "relevance_threshold": 2.5,
}


def setup_logging(debug_mode: bool = False) -> None:
    """配置日志系统"""
    level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def get_config(key: str, default=None, task: str | None = None):
    """
    获取配置项。

    优先级：
    1. ai_config.json 中的 TASK_KEY，例如 ANALYSIS_OPENAI_MODEL
    2. ai_config.json 中的 KEY
    3. 环境变量中的 TASK_KEY
    4. 环境变量中的 KEY
    5. default
    """
    if task:
        task_key = f"{task.upper()}_{key}"
        if task_key in USER_DYNAMIC_CONFIG:
            return USER_DYNAMIC_CONFIG[task_key]

    if key in USER_DYNAMIC_CONFIG:
        return USER_DYNAMIC_CONFIG[key]

    if task:
        val = os.getenv(f"{task.upper()}_{key}")
        if val is not None:
            return val

    return os.getenv(key, default)


def get_openai_task_config(task: str, default_model: str) -> OpenAIConfig:
    """
    解析某个任务使用的 OpenAI 配置。

    约定：
    - API key 和 base URL 统一使用全局 OPENAI_* 配置
    - 只有 model 允许按任务覆盖，例如 ANALYSIS_OPENAI_MODEL
    """
    return OpenAIConfig(
        api_key=get_config("OPENAI_API_KEY"),
        base_url=get_config("OPENAI_BASE_URL", OPENAI_DEFAULT_BASE_URL),
        model=get_config("OPENAI_MODEL", default_model, task=task),
    )


def log_debug(title: str, content: str) -> None:
    """Debug日志打印"""
    logger.debug(f"\n--- {title} ---\n{content}\n{'-' * 50}")
