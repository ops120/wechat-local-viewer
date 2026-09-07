from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from ..db import get_connection, meta_get, meta_set
from ..etl import run_etl, _get_counts
from ..models import ETLResult, ETLStatus

router = APIRouter()


class ETLRequest(BaseModel):
    force: Optional[bool] = False


@router.post("/etl", response_model=ETLResult)
async def trigger_etl(request: ETLRequest):
    """触发 ETL 流程"""
    try:
        result = run_etl(force=request.force)
        return ETLResult(
            mode=result['mode'],
            counts=result['counts']
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ETL 失败: {str(e)}")


@router.get("/status", response_model=ETLStatus)
async def get_status():
    """获取系统状态"""
    try:
        counts = _get_counts()
        last_etl = meta_get('last_etl_at')
        fingerprint = meta_get('source_fingerprint')
        parse_errors = int(meta_get('parse_errors') or 0)

        return ETLStatus(
            counts=counts,
            last_etl=last_etl,
            fingerprint=fingerprint,
            parse_errors=parse_errors
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取状态失败: {str(e)}")


@router.get("/logs")
async def get_logs(lines: int = 100):
    """获取最近的日志"""
    from pathlib import Path
    log_dir = Path(__file__).parent.parent.parent.parent / ".tmp" / "logs"
    log_file = log_dir / "app.log"

    if not log_file.exists():
        return {"logs": []}

    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            all_lines = f.readlines()
            recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return {"logs": [line.strip() for line in recent_lines]}
    except Exception as e:
        return {"logs": [f"读取日志失败: {str(e)}"]}


@router.post("/rebuild-fts")
async def rebuild_fts():
    """重建 FTS 索引"""
    conn = get_connection()
    try:
        conn.execute("DELETE FROM messages_fts")
        conn.execute("""
            INSERT INTO messages_fts(rowid, content, sender_display_name)
            SELECT id, content, sender_display_name FROM messages
        """)
        conn.commit()
        return {"status": "success", "message": "FTS 索引重建完成"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"重建 FTS 失败: {str(e)}")
    finally:
        conn.close()


@router.get("/stats/daily")
async def get_daily_stats(
    session: Optional[str] = None,
    days: int = 30
):
    """获取每日消息统计"""
    conn = get_connection()
    try:
        conditions = []
        params = []

        if session:
            conditions.append("session_username = ?")
            params.append(session)

        if days:
            conditions.append("create_time >= ?")
            import time
            threshold = int((time.time() - days * 86400) * 1000)
            params.append(threshold)

        where_clause = ""
        if conditions:
            where_clause = "WHERE " + " AND ".join(conditions)

        query = f"""
            SELECT
                date(create_time / 1000, 'unixepoch', 'localtime') as date,
                COUNT(*) as count,
                SUM(CASE WHEN is_self = 1 THEN 1 ELSE 0 END) as self_count
            FROM messages
            {where_clause}
            GROUP BY date
            ORDER BY date
        """

        rows = conn.execute(query, params).fetchall()

        stats = []
        for row in rows:
            stats.append({
                'date': row['date'],
                'count': row['count'],
                'self_count': row['self_count']
            })

        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计失败: {str(e)}")
    finally:
        conn.close()