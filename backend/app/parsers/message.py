import sqlite3
import json
import re
import logging
from pathlib import Path
from typing import Iterator

from ..config import DECRYPTED_DIR
from ..models import Message
from .msg_types import maybe_zstd_decompress, build_content

logger = logging.getLogger(__name__)

MSG_DIR_CANDIDATES = [
    DECRYPTED_DIR / "message",
    DECRYPTED_DIR / "db_storage" / "message",
]


def _bytes_safe(v):
    """bytes -> hex 字符串，避免 JSON 序列化失败"""
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8", errors="ignore")
        except Exception:
            return v.hex()
    return v


def _extract_sender_from_source(source_xml: str) -> tuple[str | None, str | None]:
    """从 msgsource XML 提取 sender（微信 4.1+ 的 source 多为 zstd 压缩，先解压）"""
    if not source_xml:
        return None, None
    text = maybe_zstd_decompress(source_xml).decode("utf-8", errors="ignore")
    if not text:
        return None, None
    m = re.search(r'<realChatUserName>([^<]+)</realChatUserName>', text)
    if m:
        return m.group(1), None
    m = re.search(r'<fromusr>([^<]+)</fromusr>', text)
    if m:
        return m.group(1), None
    m = re.search(r'<atuserlist>(.*?)</atuserlist>', text, re.DOTALL)
    if m:
        return m.group(1).split(",")[0].strip(), None
    return None, None


def _extract_media_md5_from_packed(packed) -> str | None:
    """packed_info_data 包含 32 字符的 md5（带长度前缀）。zstd 压缩则先解压。"""
    if not packed:
        return None
    data = maybe_zstd_decompress(packed)
    if not data:
        return None
    m = re.search(rb'[0-9a-f]{32}', data, re.IGNORECASE)
    if m:
        return m.group(0).decode("ascii")
    return None


def _parse_sysmsg_xml(xml_text: str) -> str | None:
    """解析系统消息 XML（撤回 / 拍一拍 等）。微信 4.1+ XML 结构不严格闭合，需宽松匹配。"""
    if not xml_text:
        return None
    xml_only = re.sub(r'^.*?(?=<\?xml|<sysmsg|<msg)', '', xml_text, count=1)
    try:
        # 撤回一条消息：<content>"xxx" 撤回了一条消息</time>
        if 'revokemsg' in xml_only:
            m = re.search(r'<content>(.*?)</', xml_only, re.DOTALL)
            if m:
                inner = m.group(1).strip()
                return f"[系统] {inner}" if inner else "[系统] 撤回了一条消息"
        # 拍一拍
        if '"pat"' in xml_only or '<sysmsg type="pat"' in xml_only:
            m = re.search(r'<fromusr>(.*?)</', xml_only, re.DOTALL)
            if m:
                return f"[系统] {m.group(1)} 拍了拍你"
        # 邀请/踢出等群事件
        m = re.search(r'<event>.*?<type>(\d+)</type>', xml_only, re.DOTALL)
        if m:
            plain = re.sub(r"<[^>]+>", " ", xml_only)
            plain = re.sub(r"\s+", " ", plain).strip()
            if plain:
                return f"[系统] {plain[:120]}"
    except Exception:
        pass
    return None


def _load_name2id(conn: sqlite3.Connection) -> dict[int, str]:
    """Name2Id: rowid -> username（消息表 real_sender_id 的反查表）"""
    mapping: dict[int, str] = {}
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        if "Name2Id" not in tables:
            return mapping
        for rowid, username in conn.execute("SELECT rowid, user_name FROM Name2Id"):
            if username:
                mapping[rowid] = username
    except Exception as e:
        logger.error(f"Error loading Name2Id: {e}")
    return mapping


def parse_messages(md5_to_username: dict[str, str] | None = None) -> Iterator[Message]:
    msg_dir = None
    for cand in MSG_DIR_CANDIDATES:
        if cand.exists():
            msg_dir = cand
            break
    if msg_dir is None:
        logger.warning("Message directory not found")
        return

    for db_file in sorted(msg_dir.glob("*.db")):
        if not db_file.stem.startswith("message"):
            continue  # 跳过 biz_message / media_*
        try:
            conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            name2id = _load_name2id(conn)
            tables = [r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            msg_tables = [t for t in tables if t.startswith("Msg_") and len(t) == 36]
            # 适配 微信 4.1+：每个 Msg_xx 表对应一个会话
            for tbl in msg_tables:
                session_md5 = tbl[4:]
                try:
                    rows = conn.execute(f'SELECT * FROM "{tbl}"').fetchall()
                except Exception as e:
                    logger.error(f"Error reading {tbl}: {e}")
                    continue
                for idx, row in enumerate(rows):
                    try:
                        d = dict(row)
                        # 先取二进制原值（zstd 解压需要原始字节，_bytes_safe 的 utf-8 转换会破坏魔数）
                        source_blob = d.get("source") or ""
                        if isinstance(source_blob, str):
                            source_blob = source_blob.encode("utf-8", errors="ignore")
                        packed_blob = d.get("packed_info_data") or ""
                        if isinstance(packed_blob, str):
                            packed_blob = packed_blob.encode("utf-8", errors="ignore")
                        content_bytes = d.get("message_content") or ""
                        if isinstance(content_bytes, str):
                            content_bytes = content_bytes.encode("utf-8", errors="ignore")
                        # 安全转换所有 bytes（仅用于 raw_json 存档）
                        for k, v in list(d.items()):
                            d[k] = _bytes_safe(v)

                        local_id = d.get("local_id") or idx
                        local_type = int(d.get("local_type") or 0)

                        # create_time：可能是秒或毫秒
                        ct = d.get("create_time") or 0
                        if isinstance(ct, str):
                            try:
                                ct = int(ct)
                            except Exception:
                                ct = 0
                        if ct and ct < 10**12:
                            ct = ct * 1000

                        source_xml = source_blob
                        sender, _ = _extract_sender_from_source(source_xml)

                        # real_sender_id -> Name2Id 反查（zstd source 里没有 sender，4.1+ 靠这个）
                        if not sender:
                            rsid = d.get("real_sender_id")
                            if rsid:
                                sender = name2id.get(int(rsid))

                        # 从 packed_info_data 提 media md5（用于图片消息）
                        media_md5 = _extract_media_md5_from_packed(packed_blob)

                        if local_type == 10000:
                            # 系统消息（撤回 / 拍一拍 / 群事件）
                            dec = maybe_zstd_decompress(content_bytes)
                            text = dec.decode("utf-8", errors="ignore")
                            content = _parse_sysmsg_xml(text) or text
                            if content == text and len(content) > 200:
                                content = "[系统消息]"
                        else:
                            # 文本(1)保持原文；大数类型/49 及其它小类型由 msg_types 分类
                            text, msg_sender = build_content(local_type, content_bytes)
                            if msg_sender:
                                sender = msg_sender
                            if local_type == 1 and ("<sysmsg" in text or "<?xml" in text):
                                content = _parse_sysmsg_xml(text) or text
                            else:
                                content = text or None
                        raw = json.dumps(d, ensure_ascii=False, default=str)

                        # 反查真实 session username（md5 命中则替换，否则保留 msg_<md5> 占位）
                        real_session = md5_to_username.get(session_md5) if md5_to_username else None
                        session_username = real_session or f"msg_{session_md5}"

                        yield Message(
                            session_username=session_username,
                            local_id=int(local_id),
                            create_time=int(ct),
                            sender_username=sender,
                            sender_display_name=sender,
                            local_type=local_type,
                            content=content[:2000] if content else None,
                            media_md5=media_md5,
                            is_self=0,
                            raw_json=raw,
                        )
                    except Exception as e:
                        logger.error(f"Error parsing msg {tbl} row {idx}: {e}")
                        continue
            conn.close()
        except Exception as e:
            logger.error(f"Error opening message db {db_file}: {e}")
