import sqlite3
from pathlib import Path
from typing import Iterator
import logging

from ..config import DECRYPTED_DIR
from ..models import Contact

logger = logging.getLogger(__name__)

CONTACT_DIR_CANDIDATES = [
    DECRYPTED_DIR / "contact",
    DECRYPTED_DIR / "db_storage" / "contact",
]

CONTACT_TABLE_CANDIDATES = ["contact", "Contact", "wc_contact"]


def _pick_contact_table(conn: sqlite3.Connection) -> str | None:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    names = {r[0] for r in rows}
    for cand in CONTACT_TABLE_CANDIDATES:
        if cand in names:
            return cand
    return None


def parse_contacts() -> list[Contact]:
    contacts: list[Contact] = []
    seen: set[str] = set()

    contact_dir = None
    for cand in CONTACT_DIR_CANDIDATES:
        if cand.exists():
            contact_dir = cand
            break
    if contact_dir is None:
        # 根目录 contact.json 兼容
        cj = DECRYPTED_DIR / "contact.json"
        if cj.exists():
            try:
                import json
                with open(cj, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                items = data if isinstance(data, list) else data.get("contacts", [])
                for it in items:
                    try:
                        contacts.append(Contact(**it))
                    except Exception as e:
                        logger.error(f"Error parsing contact: {e}")
            except Exception as e:
                logger.error(f"Error reading contact.json: {e}")
        return contacts

    for db_file in sorted(contact_dir.glob("*.db")):
        try:
            conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
            conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
            conn.row_factory = sqlite3.Row
            table = _pick_contact_table(conn)
            if not table:
                conn.close()
                continue
            rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            for row in rows:
                try:
                    data = dict(row)
                    # 强制字符串字段
                    for k, v in list(data.items()):
                        if isinstance(v, bytes):
                            data[k] = v.decode("utf-8", errors="ignore")
                    username = data.get("username") or data.get("userName")
                    if not username or username in seen:
                        continue
                    seen.add(username)

                    display_name = (
                        data.get("remark")
                        or data.get("alias")
                        or data.get("nick_name")
                        or data.get("nickName")
                        or username
                    )

                    contacts.append(Contact(
                        username=username,
                        local_type=data.get("local_type"),
                        alias=data.get("alias"),
                        remark=data.get("remark"),
                        nick_name=data.get("nick_name") or data.get("nickName"),
                        head_img_md5=data.get("head_img_md5") or data.get("headImgMd5"),
                        display_name=str(display_name)[:200] if display_name else None,
                        delete_flag=data.get("delete_flag", 0),
                        chat_room_notify=data.get("chat_room_notify", 0),
                        is_in_chat_room=data.get("is_in_chat_room", 0),
                    ))
                except Exception as e:
                    continue
            conn.close()
        except Exception as e:
            logger.error(f"Error reading contact db {db_file}: {e}")

    logger.info(f"Parsed {len(contacts)} contacts")
    return contacts