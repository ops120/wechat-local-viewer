from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from ..db import get_connection
from ..models import Message, MessagePage
from ..parsers.sender_resolver import resolve_display_name, clear_cache as clear_contacts_cache
from ..parsers.chatroom_alias import get_chatroom_alias
from ..parsers.media_mapper import get_media_url as _resolve_media_url

router = APIRouter()


def _resolve_sender(row) -> dict:
    """反查 sender 显示名 + media_url"""
    raw_sender = row['sender_username']
    raw_display = row['sender_display_name']
    session = row['session_username']
    alias = None
    if raw_sender and session.endswith('@chatroom'):
        alias = get_chatroom_alias(session, raw_sender)
    if alias:
        resolved = alias
    else:
        resolved = resolve_display_name(raw_sender, raw_display or "")
    md5 = row['media_md5']
    return {
        'id': row['id'],
        'session_username': row['session_username'],
        'local_id': row['local_id'],
        'create_time': row['create_time'],
        'sender_username': raw_sender,
        'sender_display_name': resolved,
        'local_type': row['local_type'],
        'content': row['content'],
        'media_md5': md5,
        'media_url': _resolve_media_url(md5, row['local_type']) if md5 else None,
        'is_self': row['is_self'],
        'raw_json': row['raw_json'],
    }


@router.get("", response_model=MessagePage)
async def get_messages(
    session: str = Query(..., description="会话 username"),
    before_ts: Optional[int] = Query(None, description="早于此时间戳的消息"),
    after_ts: Optional[int] = Query(None, description="晚于此时间戳的消息"),
    page: int = Query(1, ge=1, description="页码"),
    size: int = Query(30, ge=1, le=200, description="每页数量")
):
    """获取消息列表，按时间倒序"""
    conn = get_connection()
    try:
        # 构建查询条件
        conditions = ["session_username = ?"]
        params = [session]

        if before_ts:
            conditions.append("create_time < ?")
            params.append(before_ts)

        if after_ts:
            conditions.append("create_time > ?")
            params.append(after_ts)

        where_clause = "WHERE " + " AND ".join(conditions)

        # 查询总数（会话全量，不受 before_ts/after_ts 影响，前端据此判断是否还有更早消息）
        total = conn.execute(
            "SELECT COUNT(*) FROM messages WHERE session_username = ?",
            (session,),
        ).fetchone()[0]

        # 查询数据
        offset = (page - 1) * size
        data_query = f"""
            SELECT * FROM messages
            {where_clause}
            ORDER BY create_time DESC, local_id DESC
            LIMIT ? OFFSET ?
        """
        rows = conn.execute(data_query, params + [size, offset]).fetchall()

        items = []
        for row in rows:
            items.append(Message(**_resolve_sender(row)))

        return MessagePage(items=items, total=total, page=page, size=size)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询消息失败: {str(e)}")
    finally:
        conn.close()


@router.get("/{message_id}")
async def get_message_detail(message_id: int):
    """获取单条消息详情"""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM messages WHERE id = ?",
            (message_id,)
        ).fetchone()

        if not row:
            raise HTTPException(status_code=404, detail="消息不存在")

        return Message(**_resolve_sender(row))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询消息详情失败: {str(e)}")
    finally:
        conn.close()


@router.get("/{message_id}/context")
async def get_message_context(
    message_id: int,
    before: int = Query(5, ge=0, le=50, description="之前的消息数"),
    after: int = Query(5, ge=0, le=50, description="之后的消息数")
):
    """获取消息上下文"""
    conn = get_connection()
    try:
        # 获取目标消息
        target = conn.execute(
            "SELECT * FROM messages WHERE id = ?",
            (message_id,)
        ).fetchone()

        if not target:
            raise HTTPException(status_code=404, detail="消息不存在")

        # 获取之前的消息
        before_messages = conn.execute("""
            SELECT * FROM messages
            WHERE session_username = ? AND create_time < ?
            ORDER BY create_time DESC
            LIMIT ?
        """, (target['session_username'], target['create_time'], before)).fetchall()

        # 获取之后的消息
        after_messages = conn.execute("""
            SELECT * FROM messages
            WHERE session_username = ? AND create_time > ?
            ORDER BY create_time ASC
            LIMIT ?
        """, (target['session_username'], target['create_time'], after)).fetchall()

        # 合并结果
        context = []

        # 添加之前的消息（正序）
        for row in reversed(before_messages):
            context.append(Message(**_resolve_sender(row)))

        # 添加目标消息
        context.append(Message(**_resolve_sender(target)))

        # 添加之后的消息
        for row in after_messages:
            context.append(Message(**_resolve_sender(row)))

        return {
            'message': Message(**_resolve_sender(target)),
            'context': context
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取消息上下文失败: {str(e)}")
    finally:
        conn.close()