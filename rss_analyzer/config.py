"""
配置管理模块。

推荐用法：
- OPENAI_API_KEY / OPENAI_BASE_URL 全局共享
- ANALYSIS_OPENAI_MODEL / SUMMARY_OPENAI_MODEL 按任务切模型
- EMBEDDING_API_KEY / EMBEDDING_BASE_URL / EMBEDDING_MODEL 独立配置向量模型
"""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"
EMBEDDING_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
EMBEDDING_DEFAULT_MODEL = "text-embedding-v3"
OUTPUT_DIR = "output"
LATEST_UNREAD_FILE = os.path.join(OUTPUT_DIR, "unread_news.json")
LATEST_ANALYZED_FILE = os.path.join(OUTPUT_DIR, "analyzed_articles_latest.json")
LATEST_SUMMARY_FILE = os.path.join(OUTPUT_DIR, "summary_latest.md")


@dataclass(frozen=True)
class OpenAIConfig:
    api_key: str | None
    base_url: str
    model: str


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str | None
    base_url: str
    model: str

PROJ_CONFIG = {
    "input_file": LATEST_UNREAD_FILE,
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
    1. 环境变量中的 TASK_KEY
    2. 环境变量中的 KEY
    3. default
    """
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


def get_embedding_config() -> EmbeddingConfig:
    """
    解析 embedding 使用的独立配置。

    优先级：
    1. EMBEDDING_* 显式配置
    2. 兼容已有 DashScope / Aliyun embedding 环境变量
    3. API key 最后兜底复用 OPENAI_API_KEY

    注意：
    - 不再回退到 OPENAI_BASE_URL，避免聊天 provider 变更误伤 embedding。
    - model 默认维持 text-embedding-v3。
    """
    return EmbeddingConfig(
        api_key=(
            os.getenv("EMBEDDING_API_KEY")
            or os.getenv("DASHSCOPE_API_KEY")
            or os.getenv("ALIYUN_OPENAI_API_KEY")
            or os.getenv("OPENAI_API_KEY")
        ),
        base_url=(
            os.getenv("EMBEDDING_BASE_URL")
            or os.getenv("DASHSCOPE_BASE_URL")
            or os.getenv("ALIYUN_OPENAI_BASE_URL")
            or EMBEDDING_DEFAULT_BASE_URL
        ),
        model=os.getenv("EMBEDDING_MODEL", EMBEDDING_DEFAULT_MODEL),
    )


def log_debug(title: str, content: str) -> None:
    """Debug日志打印"""
    logger.debug(f"\n--- {title} ---\n{content}\n{'-' * 50}")
