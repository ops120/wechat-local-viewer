from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from ..db import get_connection
from ..models import SearchHit
from ..parsers.sender_resolver import resolve_display_name

router = APIRouter()


def _escape_fts(q: str) -> str:
    """把用户输入包成 FTS5 短语，中和 [ ] * ( ) 等特殊字符（"[文件]" 之类标签搜索不再报错）"""
    escaped = q.replace('"', '""')
    return f'"{escaped}"'


@router.get("", response_model=List[SearchHit])
async def search_messages(
    q: str = Query(..., min_length=1, description="搜索关键词"),
    session: Optional[str] = Query(None, description="限定会话 username"),
    before: Optional[int] = Query(None, description="早于此时间戳"),
    after: Optional[int] = Query(None, description="晚于此时间戳"),
    limit: int = Query(50, ge=1, le=200, description="返回结果数")
):
    """全文搜索消息"""
    conn = get_connection()
    try:
        fts_query = _escape_fts(q)

        # 构建 FTS 查询
        if session or before or after:
            conditions = []
            params = []

            if session:
                conditions.append("m.session_username = ?")
                params.append(session)

            if before:
                conditions.append("m.create_time < ?")
                params.append(before)

            if after:
                conditions.append("m.create_time > ?")
                params.append(after)

            where_clause = " AND ".join(conditions)

            query = f"""
                SELECT m.id, m.session_username, m.create_time, m.sender_display_name, m.sender_username,
                       m.content, m.local_type, m.is_self,
                       snippet(messages_fts, 0, '', '', '...', 20) as snippet
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                WHERE messages_fts MATCH ? AND {where_clause}
                ORDER BY m.create_time DESC
                LIMIT ?
            """
            params = [fts_query] + params + [limit]
        else:
            query = """
                SELECT m.id, m.session_username, m.create_time, m.sender_display_name, m.sender_username,
                       m.content, m.local_type, m.is_self,
                       snippet(messages_fts, 0, '', '', '...', 20) as snippet
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                WHERE messages_fts MATCH ?
                ORDER BY m.create_time DESC
                LIMIT ?
            """
            params = [fts_query, limit]

        rows = conn.execute(query, params).fetchall()

        results = []
        for row in rows:
            snippet = row['snippet'] if row['snippet'] else ''
            results.append(SearchHit(
                id=row['id'],
                session_username=row['session_username'],
                create_time=row['create_time'],
                sender_display_name=resolve_display_name(row['sender_username'] or '') or row['sender_display_name'],
                content=row['content'] if row['content'] else '',
                snippet=snippet
            ))

        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"搜索失败: {str(e)}")
    finally:
        conn.close()


@router.get("/suggest")
async def search_suggest(
    q: str = Query(..., min_length=1, description="搜索前缀"),
    limit: int = Query(10, ge=1, le=50, description="返回建议数")
):
    """搜索建议"""
    conn = get_connection()
    try:
        fts_query = f'"{q}"*'

        query = """
            SELECT DISTINCT content
            FROM messages_fts
            WHERE messages_fts MATCH ?
            AND content IS NOT NULL
            AND length(content) > 0
            LIMIT ?
        """

        rows = conn.execute(query, [fts_query, limit]).fetchall()

        suggestions = []
        for row in rows:
            content = row['content']
            if content and len(content) > 2:
                suggestions.append(content[:100])

        return suggestions
    except Exception as e:
        return []
    finally:
        conn.close()