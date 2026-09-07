from typing import Optional
import sqlite3
from ..config import DB_PATH
import logging

logger = logging.getLogger(__name__)

_contacts_cache: dict[str, str] = {}


def load_contacts_cache():
    """从中间层加载联系人到缓存"""
    global _contacts_cache
    if _contacts_cache:
        return
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT username, COALESCE(NULLIF(remark,''), NULLIF(alias,''), NULLIF(nick_name,''), NULLIF(display_name,''), username) as name FROM contacts"
        ).fetchall()
        for row in rows:
            _contacts_cache[row['username']] = row['name']
        conn.close()
    except Exception as e:
        logger.error(f"Error loading contacts cache: {e}")


def resolve_display_name(sender_username: str, fallback: str = "") -> str:
    """根据 username 解析显示名称"""
    if not sender_username:
        return fallback or "未知"
    # 先从缓存查找
    if not _contacts_cache:
        load_contacts_cache()
    if sender_username in _contacts_cache:
        return _contacts_cache[sender_username]
    # 返回 fallback 或原始 username
    return fallback or sender_username


def clear_cache():
    """清除缓存"""
    global _contacts_cache
    _contacts_cache = {}