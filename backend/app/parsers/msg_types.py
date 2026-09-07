"""微信 4.1+ 消息类型分类。

local_type 规则（实测 D:\...\message_0.db）：
- 常规类型：1 文本 / 3 图片 / 34 语音 / 43 视频 / 47 表情 / 48 位置 / 50 通话 / 10000 系统
- 大数类型：local_type = (appmsg_type << 32) | 49，如 244813135921 = (57<<32)|49
  高 32 位与解压后 XML 里 <appmsg><type>N</type> 一致；2000/2001 无 type 属性，是转账/红包。
- message_content / source 可能是 zstd 压缩（魔数 28 B5 2F FD），解压后才是明文 XML。
"""
import re
import logging

logger = logging.getLogger(__name__)

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

try:
    import zstandard as _zstd
    _ZSTD_CTX = _zstd.ZstdDecompressor()
    HAS_ZSTD = True
except ImportError:  # pragma: no cover
    _ZSTD_CTX = None
    HAS_ZSTD = False
    logger.warning("zstandard 未安装，压缩消息将无法解出内容")


def maybe_zstd_decompress(data) -> bytes:
    """zstd 魔数则解压，否则原样返回。输入可能是 bytes/str/None。"""
    if not data:
        return b""
    if isinstance(data, str):
        data = data.encode("utf-8", errors="ignore")
    if data[:4] != ZSTD_MAGIC:
        return bytes(data)
    if not HAS_ZSTD:
        return b""
    try:
        return _ZSTD_CTX.decompress(data)
    except Exception:
        return b""


# 常规类型标签
TYPE_LABELS = {
    1: "文本",
    3: "图片",
    34: "语音",
    43: "视频",
    47: "表情",
    48: "位置",
    50: "通话",
    51: "视频号",
    52: "视频号",
    10000: "系统",
}

# appmsg <type> 标签（大数类型的高 32 位）
APPMSG_LABELS = {
    1: "链接",
    2: "相册",
    3: "图片",
    4: "视频",
    5: "链接",
    6: "文件",
    7: "位置",
    8: "表情",
    9: "图文",
    10: "音乐",
    11: "音乐",
    12: "名片",
    14: "打招呼",
    15: "频道",
    16: "群接龙",
    17: "实时语音",
    18: "企业微信",
    19: "聊天记录",
    20: "卡券",
    22: "群工具",
    23: "话题",
    24: "群体预览",
    25: "群公告",
    26: "游戏",
    27: "群待办",
    28: "群待办",
    30: "直播间",
    31: "日程",
    32: "收藏",
    33: "小程序",
    34: "小程序",
    35: "小程序",
    36: "视频号",
    37: "话题",
    40: "群周报",
    41: "接龙",
    42: "AI 对话",
    47: "游戏",
    48: "团队邀约",
    50: "订单",
    51: "视频号",
    53: "接龙",
    54: "音乐",
    56: "文档",
    57: "引用",
    58: "图片",
    62: "小红书",
    63: "观看",
    66: "小程序",
    68: "连锁聊天",
    87: "快看",
    92: "语音条",
    2000: "转账",
    2001: "红包",
}


def _xml_attr(xml: str, attr: str) -> str | None:
    m = re.search(rf'{attr}="([^"]*)"', xml)
    return m.group(1) if m else None


def _xml_tag(xml: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{tag}>", xml, re.DOTALL)
    if m:
        return m.group(1).strip()
    return None


def type_label(local_type: int) -> str:
    """仅凭 local_type 给短标签（不解析内容，供导出/列表用）"""
    if local_type in TYPE_LABELS:
        return TYPE_LABELS[local_type]
    if local_type > 1000 and local_type != 10000:
        high = (local_type >> 32) & 0xFFFFFFFF
        return APPMSG_LABELS.get(high) or "应用消息"
    return f"类型{local_type}"


def describe_big_type(local_type: int, xml_text: str) -> tuple[str, str | None]:
    """大数类型 → (标签, 标题)。

    xml_text 是解压后的消息 XML（可能带 'sender:\n' 前缀）；解析失败时标签退化为 high 位映射。
    """
    high = (local_type >> 32) & 0xFFFFFFFF
    low = local_type & 0xFFFFFFFF

    if xml_text and "<sysmsg" in xml_text[:200]:
        # 系统事件 XML 混在大数类型里（如拍一拍），不再套 appmsg 标签
        plain = re.sub(r"<[^>]+>", " ", xml_text)
        plain = re.sub(r"\s+", " ", plain).strip()
        return "系统", plain[:120] or None

    label = None
    title = None

    if low == 49:
        label = APPMSG_LABELS.get(high) or ("链接" if high == 0 else f"应用消息{high}")
        if xml_text:
            # 红包/转账在 <des> 里给文案
            if high in (2000, 2001):
                des = _xml_tag(xml_text, "des") or ""
                title = re.sub(r"<[^>]+>", "", des)[:80] or None
            else:
                t = _xml_tag(xml_text, "type")
                if t and t.isdigit():
                    label = APPMSG_LABELS.get(int(t), label)
                title = _xml_tag(xml_text, "title") or None
                if title is None:
                    title = _xml_attr(xml_text, "filename")
    elif low == 48:
        label = "位置"
        if xml_text:
            title = _xml_attr(xml_text, "label") or None
    elif low == 50:
        label = "通话"
        if xml_text:
            m = re.search(r'<voicemsg[^>]*type="(\d+)"', xml_text)
            if m:
                label = "语音通话" if m.group(1) in ("1", "3") else "视频通话"
    elif low == 42:
        label = "名片"
        if xml_text:
            title = _xml_attr(xml_text, "nickname") or None
    elif low == 47:
        label = "表情"
        if xml_text:
            title = _xml_tag(xml_text, "des") or None
    elif low == 34:
        label = "语音"
        if xml_text:
            sec = _xml_attr(xml_text, "voicelength")
            if sec and sec.isdigit():
                label = f"语音 {int(sec) / 1000:.0f}s"
    else:
        label = TYPE_LABELS.get(low, f"类型{high if high else low}")

    return label, title


def build_content(local_type: int, raw_content: bytes) -> tuple[str, str | None]:
    """返回 (content 展示文本, 解出的 sender 前缀)。

    - zstd 解压后，'sender:\n' 前缀与 XML 正文分离
    - 文本(1)保持原文；其余类型生成 '[标签] 标题' 占位
    """
    text = ""
    sender = None
    if raw_content:
        dec = maybe_zstd_decompress(raw_content)
        try:
            text = dec.decode("utf-8", errors="ignore")
        except Exception:
            text = ""

    if text:
        # 'sender:\n 正文' 前缀（仅当 sender 像 ID 时采信）
        m = re.match(r"^([\w\-\.]{2,64}):\r?\n", text)
        if m:
            sender = m.group(1)
            text = text[m.end():]

    if local_type == 1:
        return text, sender

    if local_type > 1000 and local_type != 10000:
        label, title = describe_big_type(local_type, text)
    else:
        label, title = describe_big_type((0 << 32) | local_type, text)
    if title:
        return f"[{label}] {title}", sender
    return f"[{label}]", sender
