from pydantic import BaseModel
from typing import Optional, List


class Session(BaseModel):
    username: str
    type: str
    display_name: str
    avatar_md5: Optional[str] = None
    message_count: int = 0
    first_time: Optional[int] = None
    last_time: Optional[int] = None
    last_msg_preview: Optional[str] = None
    is_hidden: int = 0


class SessionDetail(BaseModel):
    session: Session
    stats: dict
    recent_messages: List[dict]


class Message(BaseModel):
    id: Optional[int] = None
    session_username: str
    local_id: int
    create_time: int
    sender_username: Optional[str] = None
    sender_display_name: Optional[str] = None
    local_type: int
    content: Optional[str] = None
    media_md5: Optional[str] = None
    media_url: Optional[str] = None
    is_self: int = 0
    raw_json: Optional[str] = None


class Contact(BaseModel):
    username: str
    alias: Optional[str] = None
    remark: Optional[str] = None
    nick_name: Optional[str] = None
    head_img_md5: Optional[str] = None
    display_name: Optional[str] = None
    local_type: Optional[int] = None
    delete_flag: Optional[int] = 0
    chat_room_notify: Optional[int] = 0
    is_in_chat_room: Optional[int] = 0


class SessionPage(BaseModel):
    items: List[Session]
    total: int
    page: int
    size: int


class MessagePage(BaseModel):
    items: List[Message]
    total: int
    page: int
    size: int


class SearchHit(BaseModel):
    id: int
    session_username: str
    create_time: int
    sender_display_name: Optional[str]
    content: str
    snippet: str


class ETLResult(BaseModel):
    mode: str
    counts: dict


class ETLStatus(BaseModel):
    counts: dict
    last_etl: Optional[str]
    fingerprint: Optional[str]
    parse_errors: int


class LLMConfig(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class LLMChatRequest(BaseModel):
    session: str
    message_ids: Optional[List[int]] = None
    prompt: str
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None