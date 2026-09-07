"""联系人 API"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
from ..db import get_connection
from ..models import Contact
from ..parsers.sender_resolver import resolve_display_name

router = APIRouter()


# local_type -> 类型名
TYPE_LABELS = {
    1: "person",   # 真人
    2: "room",     # 群聊
    3: "official", # 公众号/服务号
    4: "person",
    5: "other",
    6: "other",
    7: "other",
    0: "other",
}

# 群聊按 username 后缀判定（contact.db 会把大量群错标 local_type=1，与存储无关）
ROOM_SUFFIX = "(username LIKE '%@chatroom' OR username LIKE '%@openim')"


def _type_condition(type: Optional[str]) -> Optional[str]:
    if type == "person":
        return "local_type IN (1, 4) AND chat_room_notify = 0 AND delete_flag = 0 AND username NOT LIKE '%@chatroom' AND username NOT LIKE '%@openim'"
    if type == "room":
        return f"({ROOM_SUFFIX} OR (local_type = 2 AND chat_room_notify = 0))"
    if type == "official":
        return "local_type = 3"
    if type == "other":
        return "local_type IN (0, 5, 6, 7) AND username NOT LIKE '%@chatroom' AND username NOT LIKE '%@openim'"
    return None


@router.get("/contacts")
async def list_contacts(
    type: Optional[str] = Query(None, description="person|room|official|other"),
    keyword: Optional[str] = Query(None, description="搜索"),
    page: int = Query(1, ge=1),
    size: int = Query(30, ge=1, le=200),
):
    """联系人列表：按 type 过滤、按 display_name/username/nick_name/remark 模糊搜索"""
    conn = get_connection()
    try:
        c = conn.cursor()
        cond = _type_condition(type)
        if cond:
            total = c.execute(f"SELECT COUNT(*) FROM contacts WHERE {cond}").fetchone()[0]
        else:
            total = c.execute("SELECT COUNT(*) FROM contacts").fetchone()[0]

        where = []
        params: list = []
        if cond:
            where.append(cond)
        if keyword:
            where.append("(display_name LIKE ? OR username LIKE ? OR nick_name LIKE ? OR remark LIKE ?)")
            kw = f"%{keyword}%"
            params.extend([kw, kw, kw, kw])
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        offset = (page - 1) * size
        sql = f"""
            SELECT username, local_type, alias, remark, nick_name, head_img_md5, display_name
            FROM contacts
            {where_clause}
            ORDER BY
                CASE WHEN remark IS NOT NULL AND remark != '' THEN 0 ELSE 1 END,
                display_name
            LIMIT ? OFFSET ?
        """
        rows = c.execute(sql, params + [size, offset]).fetchall()

        items = []
        for r in rows:
            r = dict(r)
            is_room = r["username"].endswith("@chatroom") or "@openim" in r["username"]
            items.append({
                "username": r["username"],
                "type": "room" if is_room else TYPE_LABELS.get(r["local_type"], "other"),
                "local_type": r["local_type"],
                "alias": r.get("alias"),
                "remark": r.get("remark"),
                "nick_name": r.get("nick_name"),
                "head_img_md5": r.get("head_img_md5"),
                "display_name": r.get("display_name") or r.get("nick_name") or r["username"],
            })
        return {"items": items, "total": total, "page": page, "size": size}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询联系人失败: {str(e)}")
    finally:
        conn.close()


@router.get("/contacts/stats")
async def contacts_stats():
    """联系人统计：按 type 分组（群聊按后缀判定）"""
    conn = get_connection()
    try:
        rows = conn.execute(f"""
            SELECT
                SUM(CASE WHEN local_type IN (1, 4) AND chat_room_notify = 0 AND delete_flag = 0
                          AND username NOT LIKE '%@chatroom' AND username NOT LIKE '%@openim'
                    THEN 1 ELSE 0 END) AS person,
                SUM(CASE WHEN {ROOM_SUFFIX} OR (local_type = 2 AND chat_room_notify = 0)
                    THEN 1 ELSE 0 END) AS room,
                SUM(CASE WHEN local_type = 3 THEN 1 ELSE 0 END) AS official,
                SUM(CASE WHEN local_type IN (0, 5, 6, 7)
                          AND username NOT LIKE '%@chatroom' AND username NOT LIKE '%@openim'
                    THEN 1 ELSE 0 END) AS other,
                COUNT(*) AS total
            FROM contacts
        """).fetchone()
        return dict(rows) if rows else {}
    finally:
        conn.close()
