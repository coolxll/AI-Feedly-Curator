"""
工具函数模块
通用工具函数
"""
import json


def load_articles(json_file: str) -> list:
    """
    加载文章列表
    
    Args:
        json_file: JSON 文件路径
    
    Returns:
        文章列表
    """
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_articles(articles: list, json_file: str) -> None:
    """
    保存文章列表到 JSON 文件
    
    Args:
        articles: 文章列表
        json_file: 输出文件路径
    """
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)
