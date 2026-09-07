from pathlib import Path
import os

# 基础路径
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 解密数据目录：
# - 首选 .decrypted/（隐藏目录，历史约定）
# - 若不存在则回退 decrypted/（无点）—— wcdb-key-tool 的 --output 默认值是相对路径 "decrypted"，
#   在查看项目根目录跑解密时会直接输出到这里，无需再手工复制。
_DOT_DIR = BASE_DIR / ".decrypted"
_PLAIN_DIR = BASE_DIR / "decrypted"
if _DOT_DIR.exists() and any(_DOT_DIR.iterdir()):
    DECRYPTED_DIR = _DOT_DIR
else:
    DECRYPTED_DIR = _PLAIN_DIR

IMAGES_DIR = BASE_DIR / ".images"
CACHE_DIR = BASE_DIR / ".cache"
TMP_DIR = BASE_DIR / ".tmp"
LOGS_DIR = TMP_DIR / "logs"

# 确保目录存在
CACHE_DIR.mkdir(exist_ok=True)
TMP_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
IMAGES_DIR.mkdir(exist_ok=True)

# 数据库路径
DB_PATH = CACHE_DIR / "app.db"

# API 配置（默认 18787；8765/5173/8080 易冲突且 Windows 上部分被保留）
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("WCVIEWER_PORT") or os.getenv("API_PORT") or "18787")

# 媒体静态文件挂载
MEDIA_DIR = IMAGES_DIR

# 微信 FileStorage 媒体缓存目录（可选，含个人账号路径，敏感）。
# 通过环境变量 WECHAT_MEDIA_CACHE_DIR 配置；未配置时为 None，后端跳过该候选目录。
_wechat_media_cache = os.getenv("WECHAT_MEDIA_CACHE_DIR", "").strip()
WECHAT_MEDIA_CACHE_DIR = Path(_wechat_media_cache) if _wechat_media_cache else None