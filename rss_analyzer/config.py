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
    "mark_read": False,      # 是否默认标记已读
    "debug": False,         # 是否默认开启Debug
    "refresh": True,       # 是否默认刷新
    "proxy": "127.0.0.1:7890",  # 代理服务器
    "batch_scoring": True,  # 是否启用分析批量评分
    "batch_size": 10,       # 单次 LLM 评分的文章数
    "max_workers": 3,       # 批量评分的并发线程数

    # API Profile 配置 (指定使用哪个 profile，使用大写)
    # 可选值: "LOCAL_QWEN", "ALIYUN", "DEEPSEEK", None (使用默认)
    "analysis_profile": "LOCAL_GEMINI_LITE",   # 文章分析使用的 profile
    "summary_profile": "DEEPSEEK",      # 总结生成使用的 profile
    
    # 评分偏好设定 (Persona)
    "scoring_persona": """
你是一名关注广泛的资深程序员。
你的核心身份是：
1. **技术专家**：关注测试开发、DevOps、AI 编程、Vibe Coding 等前沿技术。

除了技术，你还有两个重要的兴趣领域：
2. **投资理财 (P1)**：对市场动态、宏观经济、投资策略非常敏感。
3. **国际政治 (P2)**：关注地缘政治、国际关系等大局势新闻。

打分时，请根据**这三个维度的综合价值**来评估。如果文章主要讲技术，按技术标准评；如果讲投资或政治，按其深度和价值评。
""",
    
    # Pre-filtering (前置过滤)
    "filter_keywords": ["推广", "广告", "特惠", "中奖", "开奖", "通知", "招聘"],
    "filter_min_length": 200,  # 正文最少字符数
    "filter_url_patterns": ["36kr.com/newsflashes/"],  # URL过滤模式（包含这些模式的URL会被跳过）
    
    # Dynamic Weighting (动态权重 - 百分比形式)
    # 格式: {文章类型: {维度: 权重百分比}}（总和为1.0）
    "scoring_weights": {
        "news": {
            "relevance": 0.40,                    # 相关性最重要
            "informativeness_accuracy": 0.35,     # 信息准确性次之
            "depth_opinion": 0.05,                # 资讯不需要深度！大幅降低
            "readability": 0.15,
            "non_redundancy": 0.05
        },
        "tutorial": {
            "relevance": 0.35,
            "informativeness_accuracy": 0.25,
            "depth_opinion": 0.10,
            "readability": 0.20,                  # 教程需要清晰的步骤
            "non_redundancy": 0.10                # 实用性 > 原创性
        },
        "opinion": {
            "relevance": 0.30,
            "informativeness_accuracy": 0.20,
            "depth_opinion": 0.35,                # 观点文章核心看深度
            "readability": 0.10,
            "non_redundancy": 0.05
        },
        "default": {
            "relevance": 0.35,
            "informativeness_accuracy": 0.25,
            "depth_opinion": 0.20,
            "readability": 0.15,
            "non_redundancy": 0.05
        }
    },
    
    # 相关性熔断阈值（一票否决机制）
    # 如果相关性分数低于此阈值，总分将被限制在此阈值以下
    "relevance_threshold": 2.5
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
