import hashlib
import json
from pathlib import Path
from typing import Iterator
from datetime import datetime
import logging
import sqlite3

from .config import DECRYPTED_DIR, CACHE_DIR, DB_PATH
from .db import get_connection, init_schema, meta_get, meta_set, truncate_tables
from .parsers.session import parse_sessions
from .parsers.message import parse_messages
from .parsers.contact import parse_contacts
from .parsers.sender_resolver import clear_cache

logger = logging.getLogger(__name__)


def compute_fingerprint(directory: Path) -> str:
    """计算源数据的指纹（只看 *.db 的路径+大小；mtime/-shm 会被只读连接触碰，参与计算会导致每次启动都重跑 ETL）"""
    if not directory.exists():
        return "empty"

    hasher = hashlib.md5()
    files_info = []
    for file_path in directory.rglob("*.db"):
        if file_path.is_file():
            files_info.append({
                'path': str(file_path.relative_to(directory)),
                'size': file_path.stat().st_size,
            })
    files_info.sort(key=lambda x: x['path'])
    for info in files_info:
        hasher.update(json.dumps(info).encode('utf-8'))
    return hasher.hexdigest()


def _batch_insert_messages(messages: list):
    """批量插入消息"""
    if not messages:
        return
    conn = get_connection()
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO messages
            (session_username, local_id, create_time, sender_username, sender_display_name, local_type, content, media_md5, is_self, raw_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                msg.session_username,
                msg.local_id,
                msg.create_time,
                msg.sender_username,
                msg.sender_display_name,
                msg.local_type,
                msg.content,
                msg.media_md5,
                msg.is_self,
                msg.raw_json
            ) for msg in messages
        ])
        conn.commit()
    finally:
        conn.close()


def _upsert_sessions(sessions: list):
    """更新会话信息"""
    if not sessions:
        return
    conn = get_connection()
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO sessions
            (username, type, display_name, avatar_md5, message_count, first_time, last_time, last_msg_preview, is_hidden)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                s.username, s.type, s.display_name, s.avatar_md5,
                s.message_count, s.first_time, s.last_time, s.last_msg_preview, s.is_hidden
            ) for s in sessions
        ])
        conn.commit()
    finally:
        conn.close()


def _upsert_contacts(contacts: list):
    """更新联系人信息 + 给只有 contact 没 session 的群自动建占位会话（display_name 用 contact 真名）"""
    if not contacts:
        return
    conn = get_connection()
    try:
        conn.executemany("""
            INSERT OR REPLACE INTO contacts
            (username, local_type, alias, remark, nick_name, head_img_md5, display_name,
             delete_flag, chat_room_notify, is_in_chat_room)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                c.username, c.local_type, c.alias, c.remark, c.nick_name,
                c.head_img_md5, c.display_name,
                c.delete_flag or 0, c.chat_room_notify or 0, c.is_in_chat_room or 0
            ) for c in contacts
        ])
        # 按 username 后缀判定群聊（@chatroom 或 @openim），给没建过 session 的建占位
        conn.executemany("""
            INSERT OR IGNORE INTO sessions
            (username, type, display_name, message_count, first_time, last_time, is_hidden)
            VALUES (?, 'room', ?, 0, NULL, NULL, 0)
        """, [
            (c.username, c.display_name or c.nick_name or c.username)
            for c in contacts
            if c.username.endswith('@chatroom') or '@openim' in c.username
        ])
        # 修正 display_name：session.db 的 summary 是"最后一条消息预览"（群聊和公众号尤其严重），
        # 不是会话名。会话名应与微信一致 = 通讯录名。有联系人真名的一律覆盖。
        conn.execute("""
            UPDATE sessions
            SET display_name = (
                SELECT COALESCE(NULLIF(c.display_name,''), NULLIF(c.nick_name,''), c.username)
                FROM contacts c
                WHERE c.username = sessions.username
            )
            WHERE EXISTS (
                SELECT 1 FROM contacts c
                WHERE c.username = sessions.username
                  AND COALESCE(NULLIF(c.display_name,''), NULLIF(c.nick_name,'')) IS NOT NULL
                  AND COALESCE(NULLIF(c.display_name,''), NULLIF(c.nick_name,'')) != sessions.username
            )
        """)
        conn.commit()
    finally:
        conn.close()


def run_etl(force: bool = False) -> dict:
    """运行 ETL 主流程"""
    # 初始化 schema
    init_schema()

    # 计算指纹
    fingerprint = compute_fingerprint(DECRYPTED_DIR)
    last_fingerprint = meta_get('source_fingerprint')

    # 判断是否需要运行
    if not force and last_fingerprint == fingerprint:
        return {
            'mode': 'skipped',
            'counts': _get_counts()
        }

    # 判断模式
    mode = 'incremental' if (not force and last_fingerprint) else 'full'

    # 解析错误计数
    parse_errors = 0
    total_messages = 0

    # 开始 ETL
    if mode == 'full':
        truncate_tables()

    # 解析并插入会话
    sessions = parse_sessions()
    _upsert_sessions(sessions)

    # 解析并插入联系人
    contacts = parse_contacts()
    _upsert_contacts(contacts)

    # 清除联系人缓存
    clear_cache()

    # 建立 session_username <-> md5 反向映射（微信 4.1+ 的 Msg_<md5> 表关联）
    import hashlib
    md5_to_username = {
        hashlib.md5(s.username.encode("utf-8")).hexdigest(): s.username
        for s in sessions
    }

    # 解析并批量插入消息
    batch = []
    batch_size = 5000
    for message in parse_messages(md5_to_username=md5_to_username):
        try:
            batch.append(message)
            total_messages += 1
            if len(batch) >= batch_size:
                _batch_insert_messages(batch)
                batch = []
        except Exception as e:
            parse_errors += 1
            logger.error(f"Error processing message: {e}")

    # 插入剩余批次
    if batch:
        _batch_insert_messages(batch)

    # 更新 meta
    meta_set('source_fingerprint', fingerprint)
    meta_set('last_etl_at', datetime.now().isoformat())
    meta_set('parse_errors', str(parse_errors))
    meta_set('total_messages', str(total_messages))

    # 计算会话统计
    _update_session_stats()

    return {
        'mode': mode,
        'counts': {
            'sessions': len(sessions),
            'contacts': len(contacts),
            'messages': total_messages,
            'parse_errors': parse_errors
        }
    }


def _get_counts() -> dict:
    """获取当前统计信息"""
    conn = get_connection()
    try:
        sessions_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        contacts_count = conn.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]
        messages_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        return {
            'sessions': sessions_count,
            'contacts': contacts_count,
            'messages': messages_count
        }
    finally:
        conn.close()


def _update_session_stats():
    """更新会话的统计信息"""
    conn = get_connection()
    try:
        conn.execute("""
            UPDATE sessions SET
                message_count = (SELECT COUNT(*) FROM messages WHERE messages.session_username = sessions.username),
                first_time = (SELECT MIN(create_time) FROM messages WHERE messages.session_username = sessions.username),
                last_time = (SELECT MAX(create_time) FROM messages WHERE messages.session_username = sessions.username),
                last_msg_preview = (
                    SELECT content FROM messages WHERE messages.session_username = sessions.username
                    ORDER BY create_time DESC, local_id DESC LIMIT 1
                )
        """)
        conn.commit()
    finally:
        conn.close()


# 主入口
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = run_etl(force=True)
    print(json.dumps(result, indent=2, ensure_ascii=False))