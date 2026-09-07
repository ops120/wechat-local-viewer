"""聊天记录导出 API（不包含图片二进制，只导文本 + 媒体占位）"""
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional
import sqlite3
import json
import io
from datetime import datetime, timezone, timedelta

from ..db import get_connection
from ..parsers.msg_types import type_label
from ..parsers.chatroom_alias import get_chatroom_alias, load_chatroom_aliases
from .sessions import _resolve_display

router = APIRouter()


def _ts_to_iso(ts_ms: int) -> str:
    if not ts_ms:
        return ""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone(timedelta(hours=8)))
    return dt.isoformat(timespec="seconds")


@router.get("/export")
async def export_messages(
    session: str = Query(..., description="会话 username（必填，逗号分隔多个）"),
    date: Optional[str] = Query(None, description="单日 YYYY-MM-DD（与 from/to 二选一）"),
    from_date: Optional[str] = Query(None, description="开始日期 YYYY-MM-DD"),
    to_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    format: str = Query("json", description="json | ndjson（每行一条） | txt（人类可读） | csv（Excel）"),
    include_system: bool = Query(True, description="是否包含系统消息（撤回等）"),
):
    """按日期范围导出聊天记录为 JSON / NDJSON / TXT / CSV（不包含图片二进制）"""
    # 解析日期范围
    if date:
        from_date = to_date = date
    if not from_date and not to_date:
        raise HTTPException(status_code=400, detail="需要提供 date 或 from_date + to_date")

    try:
        from_ts = int(datetime.fromisoformat(from_date).timestamp() * 1000) if from_date else 0
        to_ts = int(datetime.fromisoformat(to_date).timestamp() * 1000) + 86400000 - 1 if to_date else 99999999999999
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"日期格式错误: {e}")

    sessions = [s.strip() for s in session.split(",") if s.strip()]
    if not sessions:
        raise HTTPException(status_code=400, detail="session 不能为空")

    placeholders = ",".join("?" for _ in sessions)

    # 查会话元信息
    conn = get_connection()
    try:
        meta_rows = conn.execute(
            f"SELECT username, type, display_name FROM sessions WHERE username IN ({placeholders})",
            sessions,
        ).fetchall()
        session_meta = {r["username"]: dict(r) for r in meta_rows}

        # 查消息 + join contacts 拿 display_name
        sql = f"""
            SELECT m.id, m.session_username, m.create_time, m.sender_username,
                   m.local_type, m.content, m.media_md5,
                   c.display_name AS contact_display_name
            FROM messages m
            LEFT JOIN contacts c ON c.username = m.sender_username
            WHERE m.session_username IN ({placeholders})
              AND m.create_time >= ? AND m.create_time <= ?
        """
        params = sessions + [from_ts, to_ts]
        if not include_system:
            sql += " AND m.local_type != 10000"
        sql += " ORDER BY m.session_username, m.create_time ASC"
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    # 按 session 分组（会话名走统一的 display 兜底逻辑：群名 → 群成员别名 → username）
    load_chatroom_aliases()
    session_display = {
        sid: _resolve_display(sid, session_meta.get(sid, {}).get("display_name") or "",
                              session_meta.get(sid, {}).get("type") or "")
        for sid in sessions
    }
    by_session: dict[str, list[dict]] = {s: [] for s in sessions}
    for r in rows:
        sid = r["session_username"]
        if sid not in by_session:
            by_session[sid] = []
        contact_name = r["contact_display_name"] or r["sender_username"]
        if sid.endswith("@chatroom") or "@openim" in sid:
            # 群聊：优先群内昵称（如"领创-杨城城"），备注/昵称（如"老婆"）作后备
            sender_name = get_chatroom_alias(sid, r["sender_username"]) or contact_name
        else:
            sender_name = contact_name
        by_session[sid].append({
            "id": r["id"],
            "create_time": r["create_time"],
            "create_time_iso": _ts_to_iso(r["create_time"]),
            "sender_username": r["sender_username"],
            "sender_display_name": sender_name,
            "local_type": r["local_type"],
            "type_label": type_label(r["local_type"]),
            "content": r["content"] or "",
            "media_md5": r["media_md5"],
        })

    # 生成文件名
    if from_date == to_date:
        suffix = from_date
    else:
        suffix = f"{from_date or 'all'}_{to_date or 'now'}"

    if format == "ndjson":
        # 每行一条 JSON
        buf = io.StringIO()
        for sid, msgs in by_session.items():
            for m in msgs:
                rec = {"session": sid, "display_name": session_display.get(sid, sid), **m}
                buf.write(json.dumps(rec, ensure_ascii=False) + "\n")
        content = buf.getvalue()
        media = "application/x-ndjson"
        filename = f"export_{suffix}.ndjson"
    elif format == "txt":
        # 人类可读：按会话分组、按时间排列
        buf = io.StringIO()
        buf.write(f"# WeChat 聊天记录导出\n")
        buf.write(f"# 导出时间: {_ts_to_iso(int(datetime.now(tz=timezone(timedelta(hours=8))).timestamp() * 1000))}\n")
        buf.write(f"# 时间范围: {from_date} ~ {to_date}\n\n")
        for sid, msgs in by_session.items():
            buf.write(f"\n{'='*60}\n")
            buf.write(f"会话: {session_display.get(sid, sid)}  ({sid})\n")
            buf.write(f"消息数: {len(msgs)}\n")
            buf.write(f"{'='*60}\n")
            current_date = ""
            for m in msgs:
                date_part = m["create_time_iso"][:10]
                if date_part != current_date:
                    buf.write(f"\n----- {date_part} -----\n")
                    current_date = date_part
                sender = m["sender_display_name"] or m["sender_username"] or "未知"
                buf.write(f"[{m['create_time_iso'][11:19]}] {sender}: {m['content']}\n")
        content = buf.getvalue()
        media = "text/plain; charset=utf-8"
        filename = f"export_{suffix}.txt"
    elif format == "csv":
        # CSV：方便 Excel 打开（加 UTF-8 BOM，否则 Excel 中文乱码）
        import csv as csvmod
        buf = io.StringIO()
        writer = csvmod.writer(buf)
        writer.writerow(["session", "display_name", "create_time", "sender", "type", "content", "media_md5"])
        for sid, msgs in by_session.items():
            for m in msgs:
                writer.writerow([
                    sid, session_display.get(sid, ""),
                    m["create_time_iso"],
                    m["sender_display_name"] or m["sender_username"] or "",
                    m["type_label"],
                    m["content"] or "",
                    m["media_md5"] or "",
                ])
        content = "﻿" + buf.getvalue()
        media = "text/csv; charset=utf-8"
        filename = f"export_{suffix}.csv"
    else:
        # 单个 JSON 对象
        payload = {
            "exported_at": _ts_to_iso(int(datetime.now(tz=timezone(timedelta(hours=8))).timestamp() * 1000)),
            "date_range": [from_date, to_date],
            "total_messages": sum(len(m) for m in by_session.values()),
            "sessions": {
                sid: {
                    "display_name": session_display.get(sid, sid),
                    "type": session_meta.get(sid, {}).get("type", ""),
                    "message_count": len(msgs),
                    "messages": msgs,
                }
                for sid, msgs in by_session.items()
            },
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        media = "application/json"
        filename = f"export_{suffix}.json"

    return StreamingResponse(
        iter([content]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )