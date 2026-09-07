from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import re
import sqlite3
from ..db import get_connection
from ..models import Session, SessionPage, SessionDetail
from ..parsers.sender_resolver import resolve_display_name
from ..parsers.chatroom_alias import load_chatroom_aliases, get_first_member_alias, get_chatroom_alias
from ..config import DECRYPTED_DIR

router = APIRouter()


@router.get("/search")
async def search_sessions(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    page: int = Query(1, ge=1),
    size: int = Query(50, ge=1, le=200),
):
    """按显示名/username 模糊搜索（大小写不敏感）。

    同时匹配「解析后的显示名」——库里存的名字可能是消息预览/链接等坏值，
    用户看到的是解析后的名字，必须按看到的搜。
    会话总量在千级，Python 侧过滤足够快。
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY message_count DESC"
        ).fetchall()
        kw = q.lower()
        matched = []
        for row in rows:
            resolved = _resolve_display(row['username'], row['display_name'], row['type'])
            haystacks = (resolved or '', row['display_name'] or '', row['username'] or '')
            if any(kw in h.lower() for h in haystacks):
                matched.append((row, resolved))

        total = len(matched)
        offset = (page - 1) * size
        items = []
        for row, resolved in matched[offset:offset + size]:
            items.append(Session(
                username=row['username'],
                type=row['type'],
                display_name=resolved,
                avatar_md5=row['avatar_md5'],
                message_count=row['message_count'],
                first_time=row['first_time'],
                last_time=row['last_time'],
                last_msg_preview=row['last_msg_preview'],
                is_hidden=row['is_hidden'],
            ))
        return {"items": items, "total": total, "page": page, "size": size, "query": q}
    finally:
        conn.close()


@router.get("/stats")
async def sessions_stats():
    """会话按 type 统计（群聊按 username 后缀判定，与 contact.db 的 local_type 无关）"""
    conn = get_connection()
    try:
        rows = conn.execute("""
            SELECT
                SUM(CASE WHEN type='c2c'
                          AND username NOT LIKE '%@chatroom' AND username NOT LIKE '%@openim'
                     THEN 1 ELSE 0 END) AS c2c,
                SUM(CASE WHEN type='room' OR username LIKE '%@chatroom' OR username LIKE '%@openim'
                     THEN 1 ELSE 0 END) AS room,
                SUM(CASE WHEN type='gh' THEN 1 ELSE 0 END) AS gh,
                SUM(CASE WHEN type='notify' THEN 1 ELSE 0 END) AS notify,
                COUNT(*) AS total
            FROM sessions WHERE is_hidden = 0
        """).fetchone()
        return dict(rows) if rows else {}
    finally:
        conn.close()


# 缓存 chat_room_username -> 群名（微信 4.1+ 群名在 ext_buffer protobuf 里，
# 这里 MVP 用 chat_room.username + owner 作 fallback）
_chatroom_cache: dict[str, str] = {}


def _load_chatroom_cache():
    global _chatroom_cache
    if _chatroom_cache:
        return
    try:
        db = DECRYPTED_DIR / "contact" / "contact.db"
        if not db.exists():
            return
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
        c = conn.execute("SELECT username, owner FROM chat_room").fetchall()
        for username, owner in c:
            _chatroom_cache[username] = owner or username
        conn.close()
    except Exception:
        pass


def _resolve_display(username: str, raw: str, type_: str) -> str:
    """根据 session 类型选择 display_name 来源（群聊以后缀判定，不依赖存储的 type）"""
    # 1. 如果 raw 是真实名字（不是 YouTube 链接 / http / 消息预览 / 太短），优先用
    if raw and not _is_bad_display(raw):
        return raw
    # 2. fallback：群聊优先 contacts 真名（群昵称），其次群成员别名/群主
    is_room = type_ == "room" or "@chatroom" in username or "@openim" in username
    if is_room:
        contact_name = resolve_display_name(username, "")
        if contact_name and contact_name != username and not _is_bad_display(contact_name):
            return contact_name
        load_chatroom_aliases()
        first = get_first_member_alias(username)
        if first:
            return first
        return _chatroom_cache.get(username, username)
    return resolve_display_name(username, username)


# session.db summary 泄漏成会话名的典型特征（消息预览不是会话名）
_BAD_DISPLAY_PATTERNS = (
    "撤回了一条消息", "加入了群聊", "移出群聊", "退出群聊",
    "拍了拍", "邀请你", "邀请了", "领取红包",
)


def _is_bad_display(name: str) -> bool:
    """判断 display_name 是否是占位/坏值"""
    if not name or len(name) < 2:
        return True
    lower = name.lower()
    if lower.startswith("http") or "youtu" in lower or "wxid_" in lower:
        return True
    if any(p in name for p in _BAD_DISPLAY_PATTERNS):
        return True
    # 纯表情码（如 "[OK][强]" "[语音通话]"）——消息内容不是会话名
    if re.fullmatch(r"(\[[^\[\]]{1,12}\])+", name):
        return True
    # 全部是数字（很可能是 @chatroom 后缀的 ID）
    if all(c.isdigit() or c == '@' or c.isalpha() and c.islower() for c in name) and '@' in name:
        return True
    return False


@router.get("", response_model=SessionPage)
async def get_sessions(
    type: Optional[str] = Query(None, description="会话类型过滤: c2c/room/gh/notify/all"),
    keyword: Optional[str] = Query(None, description="搜索关键词"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(50, ge=1, le=200, description="每页数量")
):
    """获取会话列表，按 last_time 倒序。
    type 过滤：c2c/room/gh/notify。room 过滤包含 username 含 @chatroom 的所有会话（修复 contact.db 错认 local_type=1 的问题）。
    """
    conn = get_connection()
    try:
        # 构建查询条件
        conditions = []
        params = []

        if type:
            if type == "room":
                # 修复：只要 username 含 @chatroom 都算 room（包括 contact.db 错认为 c2c 的群）
                conditions.append("(type = 'room' OR username LIKE '%@chatroom' OR username LIKE '%@openim')")
            elif type == "c2c":
                # 单聊 = type=c2c 且不是 @chatroom
                conditions.append("(type = 'c2c' AND username NOT LIKE '%@chatroom' AND username NOT LIKE '%@openim')")
            else:
                conditions.append("type = ?")
                params.append(type)

        if keyword:
            conditions.append("(display_name LIKE ? OR username LIKE ? OR last_msg_preview LIKE ?)")
            keyword_pattern = f"%{keyword}%"
            params.extend([keyword_pattern, keyword_pattern, keyword_pattern])

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        # 查询总数
        count_query = f"SELECT COUNT(*) FROM sessions {where_clause}"
        total = conn.execute(count_query, params).fetchone()[0]

        # 查询数据：按最近消息时间倒序（NULL/0 的会话沉底）
        offset = (page - 1) * size
        data_query = f"""
            SELECT * FROM sessions
            {where_clause}
            ORDER BY
                CASE WHEN last_time IS NULL OR last_time = 0 THEN 1 ELSE 0 END,
                last_time DESC,
                username
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(data_query, params + [size, offset]).fetchall()

        items = []
        for row in rows:
            items.append(Session(
                username=row['username'],
                type=row['type'],
                display_name=_resolve_display(row['username'], row['display_name'], row['type']),
                avatar_md5=row['avatar_md5'],
                message_count=row['message_count'],
                first_time=row['first_time'],
                last_time=row['last_time'],
                last_msg_preview=row['last_msg_preview'],
                is_hidden=row['is_hidden']
            ))

        return SessionPage(items=items, total=total, page=page, size=size)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询会话失败: {str(e)}")
    finally:
        conn.close()


@router.get("/{username}", response_model=SessionDetail)
async def get_session_detail(username: str):
    """获取会话详情"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM sessions WHERE username = ?",
            (username,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="会话不存在")

        session = Session(
            username=row['username'],
            type=row['type'],
            display_name=_resolve_display(row['username'], row['display_name'], row['type']),
            avatar_md5=row['avatar_md5'],
            message_count=row['message_count'],
            first_time=row['first_time'],
            last_time=row['last_time'],
            last_msg_preview=row['last_msg_preview'],
            is_hidden=row['is_hidden']
        )

        # 获取统计信息
        stats = {
            'total_messages': row['message_count'],
            'first_time': row['first_time'],
            'last_time': row['last_time']
        }

        # 获取最近消息
        recent_messages = conn.execute("""
            SELECT id, session_username, local_id, create_time, sender_username,
                   sender_display_name, local_type, content, media_md5, is_self
            FROM messages
            WHERE session_username = ?
            ORDER BY create_time DESC
            LIMIT 10
        """, (username,)).fetchall()

        recent = []
        for msg in recent_messages:
            recent.append({
                'id': msg['id'],
                'create_time': msg['create_time'],
                'sender_display_name': msg['sender_display_name'] or resolve_display_name(msg['sender_username'] or ''),
                'content': msg['content'],
                'local_type': msg['local_type'],
                'is_self': msg['is_self']
            })

        return SessionDetail(
            session=session,
            stats=stats,
            recent_messages=recent
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询会话详情失败: {str(e)}")
    finally:
        conn.close()