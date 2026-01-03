"""
配置管理模块
支持多环境配置切换和Profile管理
"""
import os
import logging
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# === 用户配置区域 (方便IDE直接运行) ===
PROJ_CONFIG = {
    "input_file": "unread_news.json",
    "limit": 100,
    "mark_read": True,      # 是否默认标记已读
    "debug": False,         # 是否默认开启Debug
    "refresh": False,       # 是否默认刷新
    "proxy": "http://127.0.0.1:7890",  # 代理服务器
    
    # API Profile 配置 (指定使用哪个 profile，使用大写)
    # 可选值: "LOCAL_QWEN", "ALIYUN", "DEEPSEEK", None (使用默认)
    "analysis_profile": "LOCAL_QWEN",   # 文章分析使用的 profile
    "summary_profile": "DEEPSEEK",      # 总结生成使用的 profile
    
    # 评分偏好设定 (Persona)
    "scoring_persona": """
你是一名资深测试开发工程师，热衷于 Vibe Coding（追求编码的流畅感、创造力和美感，不仅仅是功能实现）。
你的关注点包括：
1. 测试开发、自动化测试、质量保障(QA)的前沿技术和实践。
2. 提升研发效能的工具和方法（DevOps, CI/CD）。
3. AI 辅助编程、智能测试生成等能带来"心流"体验的技术。
4. 代码的优雅性、架构的整洁度。
5. 拒绝枯燥的 CRUD、过时的技术堆砌和毫无新意的八股文。
""",
    
    # Pre-filtering (前置过滤)
    "filter_keywords": ["推广", "广告", "特惠", "中奖", "开奖", "通知", "招聘"],
    "filter_min_length": 200,  # 正文最少字符数
    
    # Dynamic Weighting (动态权重)
    # 格式: {文章类型: {维度: 权重}}
    "scoring_weights": {
        "news": {"relevance": 2, "informativeness_accuracy": 4, "depth_opinion": 1, "readability": 2, "non_redundancy": 1},
        "tutorial": {"relevance": 2, "informativeness_accuracy": 3, "depth_opinion": 1, "readability": 4, "non_redundancy": 1},
        "opinion": {"relevance": 2, "informativeness_accuracy": 2, "depth_opinion": 4, "readability": 2, "non_redundancy": 2},
        "default": {"relevance": 2, "informativeness_accuracy": 2, "depth_opinion": 2, "readability": 2, "non_redundancy": 1}
    }
}
# ==========================================

# 配置日志
logger = logging.getLogger(__name__)


def setup_logging(debug_mode: bool = False) -> None:
    """配置日志系统"""
    level = logging.DEBUG if debug_mode else logging.INFO
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # 将HTTP请求日志设置为WARNING级别，避免干扰
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


def get_config(key: str, default=None, profile: str = None):
    """
    获取配置项，支持多环境配置切换。
    
    逻辑：
    1. 如果指定了 profile 参数，优先使用该 profile
    2. 否则检查环境变量 ACTIVE_PROFILE
    3. 如果存在 profile，优先查找 {PROFILE}_{KEY} 的环境变量
    4. 如果未找到 profile 特有的配置，回退到默认 KEY
    
    Args:
        key: 配置键名
        default: 默认值
        profile: 指定使用的 profile (例如: "LOCAL_QWEN", "ALIYUN")
    
    Returns:
        配置值
    """
    # 优先使用传入的 profile，否则从环境变量读取
    active_profile = profile or os.getenv("ACTIVE_PROFILE")
    
    if active_profile:
        # 尝试查找带前缀的配置 (profile 已经是大写)
        prefixed_key = f"{active_profile}_{key}"
        val = os.getenv(prefixed_key)
        if val is not None:
            return val
    
    # 回退到默认配置
    return os.getenv(key, default)


def log_debug(title: str, content: str) -> None:
    """Debug日志打印"""
    logger.debug(f"\n--- {title} ---\n{content}\n{'-' * 50}")
