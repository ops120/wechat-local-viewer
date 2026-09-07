from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import logging
from pathlib import Path

from .config import API_HOST, API_PORT, MEDIA_DIR, LOGS_DIR, WECHAT_MEDIA_CACHE_DIR
from .db import init_schema

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOGS_DIR / "app.log", encoding='utf-8')
    ]
)

# 创建 FastAPI 应用
app = FastAPI(title="WeChat Local Viewer", version="0.1.0")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化数据库
init_schema()

# 挂载静态文件（媒体）— 同时支持 .images 和微信 FileStorage 缓存（通过环境变量配置）
if MEDIA_DIR.exists():
    app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")
if WECHAT_MEDIA_CACHE_DIR is not None and WECHAT_MEDIA_CACHE_DIR.exists():
    app.mount("/filestorage", StaticFiles(directory=str(WECHAT_MEDIA_CACHE_DIR)), name="filestorage")


# 健康检查
@app.get("/health")
async def health_check():
    return {"status": "ok"}


# 导入 API 路由
from .api import sessions, messages, search, llm, admin, contacts, export
app.include_router(sessions.router, prefix="/api/sessions")
app.include_router(messages.router, prefix="/api/messages")
app.include_router(search.router, prefix="/api/search")
app.include_router(llm.router, prefix="/api/llm")
app.include_router(admin.router, prefix="/api/admin")
app.include_router(contacts.router, prefix="/api/contacts")
app.include_router(export.router, prefix="/api")


# 前端静态构建产物
from fastapi.responses import FileResponse, JSONResponse
FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/")
    @app.get("/{path:path}")
    async def spa_fallback(path: str = ""):
        if path.startswith("api/") or path.startswith("media/") or path.startswith("filestorage/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        # dist 里的真实文件（favicon.ico / robots.txt 等）优先直接返回
        target = (FRONTEND_DIST / path).resolve()
        if path and target.is_file() and str(target).startswith(str(FRONTEND_DIST.resolve())):
            return FileResponse(target)
        index = FRONTEND_DIST / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse({"detail": "frontend not built"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)