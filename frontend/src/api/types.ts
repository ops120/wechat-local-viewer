// API 类型定义

export interface Session {
  username: string
  type: string
  display_name: string
  avatar_md5?: string
  message_count: number
  first_time?: number
  last_time?: number
  last_msg_preview?: string
  is_hidden: number
}

export interface SessionDetail {
  session: Session
  stats: Record<string, any>
  recent_messages: Array<Record<string, any>>
}

export interface SessionPage {
  items: Session[]
  total: number
  page: number
  size: number
}

export interface Message {
  id?: number
  session_username: string
  local_id: number
  create_time: number
  sender_username?: string
  sender_display_name?: string
  local_type: number
  content?: string
  media_md5?: string
  is_self: number
  raw_json?: string
}

export interface MessagePage {
  items: Message[]
  total: number
  page: number
  size: number
}

export interface SearchHit {
  id: number
  session_username: string
  create_time: number
  sender_display_name?: string
  content: string
  snippet: string
}

export interface ETLStatus {
  counts: { sessions: number; contacts: number; messages: number }
  last_etl?: string
  fingerprint?: string
  parse_errors: number
}

export interface LLMConfig {
  base_url: string
  api_key: string
  model: string
}

export interface LLMChatRequest {
  session: string
  message_ids?: number[]
  prompt: string
  base_url?: string
  api_key?: string
  model?: string
}