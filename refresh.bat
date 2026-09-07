@echo off
chcp 65001 >nul
title WeChat Local Viewer - 一键刷新

setlocal
cd /d "%~dp0"

REM 取消代理（用国内镜像）
set npm_config_proxy=
set npm_config_https_proxy=

echo ========================================
echo   WeChat Local Viewer - 增量刷新
echo ========================================
echo.

REM 1) 后端 ETL (force=true 全量重建)
echo [1/2] 重跑 ETL (从 .decrypted/ 读 .db 入库中间层)...
curl -s -X POST -H "Content-Type: application/json" -d "{\"force\": true}" http://127.0.0.1:18787/api/admin/etl
echo.
echo.

REM 2) 提示用户：如需最新数据，请先跑 wcdb-key-tool 重新解密
echo [2/2] 重新解密 .db (可选 - 如果要看微信里的最新消息)
echo.
echo   微信 4.x Windows 解密流程:
echo     1. 保持微信运行并登录
echo     2. 用管理员权限运行 PowerShell
echo     3. 设置环境变量 WECHAT_DB_DIR 指向微信 db_storage 目录后，执行:
echo        python scripts\run_decrypt.py
echo.
echo   解密后 .decrypted/ 目录会更新，再重跑 ETL 即可看到新消息。
echo.

echo ========================================
echo   完成后浏览器刷新 http://127.0.0.1:18787/ 即可看新数据
echo ========================================
echo.
pause
