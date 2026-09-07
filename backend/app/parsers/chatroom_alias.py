"""从 chat_room.ext_buffer 解析每个成员的「群内昵称」(wxid → displayName)"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from typing import Iterator
import logging

from ..config import DECRYPTED_DIR

logger = logging.getLogger(__name__)

# 缓存: (chatroom_username, member_wxid) -> displayName
_alias_cache: dict[tuple[str, str], str] = {}
_loaded = False


def _parse_varint(data: bytes, pos: int) -> tuple[int, int]:
    val = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        val |= (b & 0x7f) << shift
        if not (b & 0x80):
            return val, pos + 1
        shift += 7
        pos += 1
    return val, pos


def _parse_member(buf: bytes) -> tuple[str | None, str | None]:
    """解析单条 Member entry: field 1 = wxid, field 2 = displayName"""
    wxid = None
    display = None
    pos = 0
    while pos < len(buf):
        tag, pos = _parse_varint(buf, pos)
        fno = tag >> 3
        wtype = tag & 7
        if wtype == 2:
            length, pos = _parse_varint(buf, pos)
            value = buf[pos:pos + length]
            pos += length
            try:
                s = value.decode("utf-8")
                if fno == 1:
                    wxid = s
                elif fno == 2:
                    display = s
            except Exception:
                pass
        elif wtype == 0:
            _, pos = _parse_varint(buf, pos)
        elif wtype == 1:
            pos += 8
        elif wtype == 5:
            pos += 4
        else:
            break
    return wxid, display


def _parse_chatroom(data: bytes) -> Iterator[tuple[str, str]]:
    """解析 chat_room.ext_buffer 顶层 field 1 (Members[])"""
    pos = 0
    while pos < len(data):
        tag, pos = _parse_varint(data, pos)
        fno = tag >> 3
        wtype = tag & 7
        if wtype == 2:
            length, pos = _parse_varint(data, pos)
            value = data[pos:pos + length]
            pos += length
            if fno == 1:  # Member 数组
                wxid, display = _parse_member(value)
                if wxid and display:
                    yield wxid, display
        elif wtype == 0:
            _, pos = _parse_varint(data, pos)
        elif wtype == 1:
            pos += 8
        elif wtype == 5:
            pos += 4
        else:
            break


def load_chatroom_aliases(force: bool = False) -> None:
    """扫描所有 chat_room.ext_buffer，建立 wxid 在每个群里的昵称映射"""
    global _loaded
    if _loaded and not force:
        return
    _alias_cache.clear()
    contact_db = DECRYPTED_DIR / "contact" / "contact.db"
    if not contact_db.exists():
        _loaded = True
        return
    try:
        conn = sqlite3.connect(f"file:{contact_db}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        for row in conn.execute("SELECT username, ext_buffer FROM chat_room").fetchall():
            chatroom = row["username"]
            buf = row["ext_buffer"]
            if not buf:
                continue
            for wxid, display in _parse_chatroom(bytes(buf)):
                _alias_cache[(chatroom, wxid)] = display
        conn.close()
        logger.info(f"Loaded {len(_alias_cache)} chatroom member aliases")
    except Exception as e:
        logger.error(f"load_chatroom_aliases error: {e}")
    _loaded = True


def get_chatroom_alias(chatroom_username: str, member_wxid: str) -> str | None:
    if not _loaded:
        load_chatroom_aliases()
    return _alias_cache.get((chatroom_username, member_wxid))


def get_first_member_alias(chatroom_username: str) -> str | None:
    """返回该群第一个成员的昵称（用作群名 fallback）"""
    if not _loaded:
        load_chatroom_aliases()
    for (room, _wxid), display in _alias_cache.items():
        if room == chatroom_username:
            return display
    return None