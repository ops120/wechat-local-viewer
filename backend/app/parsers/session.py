import sqlite3
from pathlib import Path
from typing import Iterator
import logging

from ..config import DECRYPTED_DIR
from ..models import Session

logger = logging.getLogger(__name__)

# 适配 微信 4.1+ / iOS / Windows 不同变体
SESSION_DIR_CANDIDATES = [
    DECRYPTED_DIR / "session",
    DECRYPTED_DIR / "db_storage" / "session",
]

# 表名候选（按优先级）
SESSION_TABLE_CANDIDATES = ["SessionTable", "session", "Session"]


def _pick_session_table(conn: sqlite3.Connection) -> str | None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r[0] for r in rows}
    for cand in SESSION_TABLE_CANDIDATES:
        if cand in names:
            return cand
    return None


def parse_sessions() -> list[Session]:
    """解析会话数据 — 适配 微信 4.1+ / iOS / Windows 多种变体"""
    sessions: list[Session] = []
    seen_usernames: set[str] = set()

    session_dir = None
    for cand in SESSION_DIR_CANDIDATES:
        if cand.exists():
            session_dir = cand
            break
    if session_dir is None:
        logger.warning("Session directory not found")
        return sessions

    for db_file in sorted(session_dir.glob("*.db")):
        try:
            conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            table = _pick_session_table(conn)
            if not table:
                logger.warning(f"No session table found in {db_file}")
                conn.close()
                continue

            rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            for row in rows:
                row = dict(row)
                username = row.get("username") or row.get("userName") or row.get("UsrName")
                if not username or username in seen_usernames:
                    continue
                seen_usernames.add(username)

                # 字段映射（多 variant）
                sess_type = row.get("type")
                # 微信 4.1+ session.db 的 type 字段不可靠，按 username 后缀判断
                # （contact.db 会把群误标 local_type=1，这里与存储无关，一律以后缀为准）
                if "@chatroom" in username or "@openim" in username:
                    sess_type = "room"
                elif username.startswith("gh_") or username.startswith("gh."):
                    sess_type = "gh"
                else:
                    sess_type = "c2c"

                display_name = (
                    row.get("summary")
                    or row.get("display_name")
                    or row.get("displayName")
                    or row.get("nick_name")
                    or username
                )
                # 群聊的 summary 是"最后一条消息预览"（撤回/链接等），不是群名——先用 username 占位，
                # 真名由 _upsert_contacts 从 contacts 表回填
                if "@chatroom" in username or "@openim" in username:
                    display_name = username

                # 时间戳
                last_ts = row.get("last_timestamp") or row.get("lastTimestamp") or row.get("last_time")
                if last_ts and last_ts < 10**12:
                    last_ts = last_ts * 1000  # 秒 → 毫秒

                first_ts = row.get("first_timestamp") or row.get("first_time")

                msg_count = row.get("message_count") or row.get("messageCount") or 0

                sessions.append(Session(
                    username=username,
                    type=str(sess_type) if sess_type else "c2c",
                    display_name=str(display_name)[:200],
                    avatar_md5=row.get("avatar_md5") or row.get("avatarMd5"),
                    message_count=0,  # ETL 后用 _update_session_stats 从 messages 表实时统计
                    first_time=int(first_ts) if first_ts else None,
                    last_time=int(last_ts) if last_ts else None,
                    last_msg_preview=row.get("last_msg_preview") or row.get("lastMessagePreview"),
                    is_hidden=int(row.get("is_hidden") or 0),
                ))
            conn.close()
        except Exception as e:
            logger.error(f"Error opening session db {db_file}: {e}")

    # 微信 4.1+ 补：从 contact.db 的 chat_room 表拿所有 @chatroom 群
    # 这些 session 也要建占位行，messages ETL 才能通过 md5 映射到正确 session
    try:
        contact_db = DECRYPTED_DIR / "contact" / "contact.db"
        if contact_db.exists():
            conn = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
            conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
            added = 0
            for row in conn.execute("SELECT username FROM chat_room").fetchall():
                username = row[0]
                if username and username not in seen_usernames and ("@chatroom" in username or "@openim" in username):
                    seen_usernames.add(username)
                    sessions.append(Session(
                        username=username,
                        type="room",
                        display_name=username,  # 后用 contact 真名覆盖
                        avatar_md5=None,
                        message_count=0,
                        first_time=None,
                        last_time=None,
                        last_msg_preview=None,
                        is_hidden=0,
                    ))
                    added += 1
            conn.close()
            logger.info(f"Added {added} chatroom sessions from contact.db")
    except Exception as e:
        logger.error(f"Error loading chat_room from contact.db: {e}")

    logger.info(f"Parsed {len(sessions)} sessions")
    return sessions