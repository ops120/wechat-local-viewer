"""图片索引：按 packed md5 在多个源里找缩略图/原图"""
import os
import re
from pathlib import Path
import logging

from ..config import IMAGES_DIR, WECHAT_MEDIA_CACHE_DIR

logger = logging.getLogger(__name__)

# 候选路径（按优先级降序）
# 注意：缩略图优先（_t / _t_W）— 体积小、加载快
CANDIDATE_DIRS = [
    # 微信 FileStorage 缓存（缩略图）— 通过环境变量 WECHAT_MEDIA_CACHE_DIR 配置
    WECHAT_MEDIA_CACHE_DIR,
    # .images（微信 4.1+ 同步缓存缩略图 + restore_images.py 还原产物）
    IMAGES_DIR,
    # 其它候选
    Path(os.path.expandvars(r"%APPDATA%\Tencent\WeChat\FileStorage")),
    Path(os.path.expandvars(r"%APPDATA%\Tencent\xwechat\FileStorage")),
]

# <md5>[_后缀].<图片扩展名>，如 42ae..._t_W.jpg / 5e0a..._W.png / 0bd0....jpg
NAME_RE = re.compile(
    r"^([0-9a-fA-F]{32})(?:_([a-zA-Z0-9_]+))?\.(jpg|jpeg|png|gif|webp)$",
    re.IGNORECASE,
)

# 缓存: media_md5 (32 hex) -> 绝对路径
_path_cache: dict[str, str | None] = {}
_loaded = False


def _register(root: str, f: str, stats: dict) -> None:
    m = NAME_RE.match(f)
    if not m:
        return
    md5 = m.group(1).lower()
    suffix = m.group(2) or ""
    is_thumb = suffix.lower().startswith("t")
    if is_thumb:
        stats["thumb"] += 1
    else:
        stats["orig"] += 1
    if md5 not in _path_cache:
        _path_cache[md5] = os.path.join(root, f)


def _build_index():
    """扫所有候选目录，建 packed md5 -> 缩略图/原图路径 索引（缩略图优先）"""
    global _loaded
    if _loaded:
        return
    stats = {"thumb": 0, "orig": 0}

    dirs = [d for d in CANDIDATE_DIRS if d is not None and d.exists()]
    for base_dir in dirs:
        # 第一遍只登记缩略图，第二遍补原图（已登记的不覆盖）
        for want_thumb in (True, False):
            for root, _, fs in os.walk(base_dir):
                for f in fs:
                    m = NAME_RE.match(f)
                    if not m:
                        continue
                    is_thumb = (m.group(2) or "").lower().startswith("t")
                    if is_thumb == want_thumb:
                        _register(root, f, stats)

    _loaded = True
    logger.info(f"media index built: {len(_path_cache)} entries, "
                f"thumbs={stats['thumb']} origs={stats['orig']} from {len(dirs)} dirs")


def find_image_path(md5: str) -> Path | None:
    if not md5:
        return None
    _build_index()
    p = _path_cache.get(md5.lower())
    if p:
        return Path(p)
    return None


def get_media_url(md5: str, media_type: int = 3) -> str | None:
    if not md5:
        return None
    p = find_image_path(md5)
    if p and p.exists():
        # FileStorage Cache 在 Documents 目录下，走 /filestorage/<相对路径>
        try:
            rel = p.relative_to(IMAGES_DIR)
            return f"/media/{rel.as_posix()}"
        except ValueError:
            if WECHAT_MEDIA_CACHE_DIR is not None:
                try:
                    rel_fs = p.relative_to(WECHAT_MEDIA_CACHE_DIR)
                    return f"/filestorage/{rel_fs.as_posix()}"
                except ValueError:
                    return None
            return None
    return None


def get_media_path(md5: str) -> Path | None:
    """返回绝对路径（给 API 层用于自定义路由）"""
    return find_image_path(md5)
