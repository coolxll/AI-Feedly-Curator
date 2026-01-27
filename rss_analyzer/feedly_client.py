"""
Feedly API 客户端模块
处理与 Feedly 服务的所有交互
"""
import os
import json
import logging
import requests
from typing import Optional

from .config import PROJ_CONFIG


logger = logging.getLogger(__name__)

# Feedly 配置文件路径 (工作目录)
FEEDLY_CONFIG_FILE = os.path.join(os.getcwd(), 'feedly_config.json')


def load_feedly_config() -> dict | None:
    """加载 Feedly 配置"""
    if os.path.exists(FEEDLY_CONFIG_FILE):
        with open(FEEDLY_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return None


def get_feedly_headers(token: str) -> dict:
    """获取 Feedly API 请求头"""
    return {
        'Authorization': f'OAuth {token}'
    }


def _get_proxy() -> dict | None:
    """获取代理配置"""
    proxy = os.getenv("HTTP_PROXY") or os.getenv("HTTPS_PROXY") or PROJ_CONFIG.get("proxy")
    return {"http": proxy, "https": proxy} if proxy else None


def feedly_fetch_unread(stream_id: Optional[str] = None, limit: int = 999) -> list | None:
    """
    从 Feedly 获取未读文章
    
    Args:
        stream_id: Feedly 流 ID，默认为所有文章
        limit: 获取文章数量限制
    
    Returns:
        文章列表，失败返回 None
    """
    config = load_feedly_config()
    if not config:
        logger.error("Feedly未配置，无法获取未读文章")
        return None
    
    token = config['token']
    user_id = config['user_id']
    base_url = "https://cloud.feedly.com/v3"
    
    target_stream = stream_id or f"user/{user_id}/category/global.all"

    try:
        articles = []
        continuation = None
        
        while len(articles) < limit:
            # Calculate remaining needed, but cap at 1000 per request (Feedly API limit usually)
            remaining = limit - len(articles)
            batch_size = min(remaining, 1000)
            
            params = {
                'streamId': target_stream,
                'count': batch_size,
                'unreadOnly': 'true'
            }
            if continuation:
                params['continuation'] = continuation
            
            response = requests.get(
                f"{base_url}/streams/contents", 
                headers=get_feedly_headers(token), 
                params=params,
                proxies=_get_proxy()
            )
            
            if response.status_code == 401:
                logger.error("Feedly认证失败，请检查token")
                return None if not articles else articles
            if response.status_code != 200:
                logger.error(f"Feedly API错误: {response.status_code} - {response.text}")
                return None if not articles else articles

            data = response.json()
            
            if 'items' in data:
                for entry in data['items']:
                    article = {
                        'title': entry.get('title', 'No Title'),
                        'link': entry.get('alternate', [{}])[0].get('href', '') if entry.get('alternate') else '',
                        'published': entry.get('published', 0),
                        'summary': entry.get('summary', {}).get('content', '') or entry.get('content', {}).get('content', ''),
                        'id': entry.get('id', ''),
                        'origin': entry.get('origin', {}).get('title', '')
                    }
                    articles.append(article)
            
            # Check for continuation token
            continuation = data.get('continuation')
            if not continuation:
                break
                
            logger.debug(f"Fetched {len(articles)}/{limit} articles... (Continuating)")
        
        # Trim to exact limit if we over-fetched (though unlikely with logic above)
        return articles[:limit]
    except Exception as e:
        logger.error(f"获取Feedly未读文章异常: {str(e)}")
        import traceback
        import sys
        traceback.print_exc(file=sys.stderr)
        return None


def feedly_mark_read(article_ids: list | str) -> bool:
    """
    标记文章为已读
    
    Args:
        article_ids: 文章 ID 或 ID 列表
    
    Returns:
        是否成功
    """
    config = load_feedly_config()
    if not config:
        logger.error("未找到 Feedly 配置，无法标记已读")
        return False
    
    token = config['token']
    base_url = "https://cloud.feedly.com/v3"

    if isinstance(article_ids, str):
        article_ids = [article_ids]
        
    try:
        data = {
            "action": "markAsRead",
            "type": "entries",
            "entryIds": article_ids
        }
        response = requests.post(
            f"{base_url}/markers", 
            headers=get_feedly_headers(token), 
            json=data,
            proxies=_get_proxy()
        )
        
        if response.status_code == 200:
            logger.info(f"成功标记 {len(article_ids)} 篇文章为已读")
            return True
        else:
            logger.error(f"标记已读失败: {response.status_code} - {response.text}")
            return False
    except Exception as e:
        logger.error(f"标记已读异常: {str(e)}")
        return False
