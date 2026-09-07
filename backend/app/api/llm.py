from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
import json
import asyncio
from ..db import get_connection
from ..llm.openai_compat import OpenAICompatClient
from ..models import LLMConfig, LLMChatRequest
from ..parsers.sender_resolver import resolve_display_name
from ..parsers.chatroom_alias import get_chatroom_alias, load_chatroom_aliases

router = APIRouter()

default_config = LLMConfig(base_url="", api_key="", model="")


@router.get("/config", response_model=LLMConfig)
async def get_llm_config():
    """获取 LLM 配置（从环境变量）"""
    import os
    return LLMConfig(
        base_url=os.getenv("LLM_BASE_URL", ""),
        api_key=os.getenv("LLM_API_KEY", ""),
        model=os.getenv("LLM_MODEL", ""),
    )


@router.post("/config")
async def set_llm_config(config: LLMConfig):
    """设置 LLM 配置（仅内存缓存）"""
    global default_config
    default_config = config
    return {"status": "success"}


@router.post("/chat")
async def chat(request: LLMChatRequest):
    """LLM 流式聊天

    配置优先级：请求体自带（前端设置面板保存的）> 后端内存缓存 > 环境变量。
    之前只用后端 default_config，导致前端配了也不生效。
    """
    if not request.session:
        raise HTTPException(status_code=400, detail="缺少会话参数")

    messages_text = _collect_messages(request)
    if not messages_text:
        raise HTTPException(status_code=400, detail="没有找到相关消息")

    import os
    base_url = request.base_url or default_config.base_url or os.getenv("LLM_BASE_URL", "")
    api_key = request.api_key or default_config.api_key or os.getenv("LLM_API_KEY", "")
    model = request.model or default_config.model or os.getenv("LLM_MODEL", "")

    if not base_url or not model:
        raise HTTPException(
            status_code=400,
            detail="LLM 未配置：请在页面右上角设置里填写 Base URL / API Key / Model（支持 OpenAI / DeepSeek / Ollama 等兼容协议）",
        )

    client = OpenAICompatClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
    )

    system_prompt = (
        "你是一个微信聊天记录分析助手。请根据提供的聊天记录回答用户的问题。"
        "如果聊天记录不足以回答问题，请明确说明。回答要简洁、准确、客观。"
    )

    llm_messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"聊天记录：\n{messages_text}\n\n用户问题：{request.prompt}"},
    ]

    return StreamingResponse(
        _stream_response(client, llm_messages),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


def _collect_messages(request: LLMChatRequest) -> str:
    """收集消息内容"""
    load_chatroom_aliases()
    conn = get_connection()
    try:
        messages = []

        if request.message_ids and len(request.message_ids) > 0:
            placeholders = ','.join(['?' for _ in request.message_ids])
            query = f"""
                SELECT create_time, sender_username, sender_display_name, content, is_self, session_username
                FROM messages
                WHERE id IN ({placeholders})
                ORDER BY create_time
            """
            rows = conn.execute(query, request.message_ids).fetchall()
        else:
            query = """
                SELECT create_time, sender_username, sender_display_name, content, is_self, session_username
                FROM messages
                WHERE session_username = ?
                ORDER BY create_time DESC
                LIMIT 100
            """
            rows = conn.execute(query, [request.session]).fetchall()
            rows = list(reversed(rows))

        for row in rows:
            sender = "我" if row['is_self'] == 1 else (
                (row['session_username'].endswith('@chatroom') or '@openim' in row['session_username'])
                and get_chatroom_alias(row['session_username'], row['sender_username'])
                or resolve_display_name(row['sender_username'] or '')
                or row['sender_display_name']
                or "未知"
            )
            content = row['content'] or "[非文本消息]"
            import datetime
            dt = datetime.datetime.fromtimestamp(row['create_time'] / 1000)
            time_str = dt.strftime("%Y-%m-%d %H:%M")
            messages.append(f"[{time_str}] {sender}: {content}")

        return "\n".join(messages)
    finally:
        conn.close()


async def _stream_response(client: OpenAICompatClient, messages: list):
    """流式响应生成器（SSE 格式）"""
    try:
        yield f"data: {json.dumps({'type': 'start'})}\n\n"
        for chunk in client.stream(messages):
            if chunk:
                yield f"data: {json.dumps({'type': 'content', 'content': chunk}, ensure_ascii=False)}\n\n"
                await asyncio.sleep(0.01)
        yield f"data: {json.dumps({'type': 'end'})}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'error': str(e)}, ensure_ascii=False)}\n\n"