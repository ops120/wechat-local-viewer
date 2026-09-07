@echo off
title WeChat Local Viewer

setlocal
cd /d "%~dp0"

REM 取消代理（用国内镜像）
set npm_config_proxy=
set npm_config_https_proxy=
set npm_config_registry=https://registry.npmmirror.com
set npm_config_maxsockets=4
set npm_config_audit=false
set npm_config_fund=false

echo ========================================
echo   WeChat Local Viewer 一键启动
echo   后端 18787 / 前端 15713
echo ========================================
echo.

REM 端口检测
echo [检查] 端口 18787 ...
python -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', 18787)); s.close(); print('  端口 18787 可用')" 2>nul
if errorlevel 1 (
    echo  [错误] 端口 18787 被占用，请先 stop 已运行的服务
    pause
    exit /b 1
)

REM 创建 venv（如不存在）
if not exist "backend\.venv\Scripts\python.exe" (
    echo [1/5] 创建 Python 虚拟环境 ...
    python -m venv backend\.venv
)

REM 安装后端依赖（仅当关键包缺失时才联网安装）
echo [2/5] 检查后端依赖 ...
backend\.venv\Scripts\python.exe -c "import fastapi, uvicorn, zstandard" >nul 2>nul
if errorlevel 1 (
    backend\.venv\Scripts\python.exe -m pip install -q -r backend\requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
)

REM 安装前端依赖（如未装）
if not exist "frontend\node_modules" (
    echo [3/5] 安装前端依赖（首次较慢）...
    cd /d "%~dp0frontend"
    call npm install --no-audit --no-fund --loglevel=error
    cd /d "%~dp0"
)

REM 前端构建产物检查（后端直接托管 dist，没有就现场构建）
if not exist "frontend\dist\index.html" (
    echo [3/5] 未找到 frontend\dist，构建前端 ...
    cd /d "%~dp0frontend"
    call npm run build
    cd /d "%~dp0"
)

REM 数据导入（ETL）：源数据没变化时自动跳过
echo [4/5] 同步数据（ETL）...
cd /d "%~dp0backend"
.venv\Scripts\python.exe -c "import sys; sys.path.insert(0, '.'); from app.etl import run_etl; r = run_etl(); print('  ETL:', r['mode'], r['counts'])"
cd /d "%~dp0"

REM 启动后端服务
echo [5/5] 启动后端服务（端口 18787）...
start "WeChat Backend" cmd /c "cd /d %~dp0backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 18787"

REM 等服务启动
%SystemRoot%\System32\timeout.exe /t 3 /nobreak >nul

REM 打开浏览器
start "" "http://127.0.0.1:18787/"

echo.
echo ========================================
echo   启动完成！
echo   浏览器: http://127.0.0.1:18787/
echo   API 文档: http://127.0.0.1:18787/docs
echo   停止服务: 任务管理器关 WeChat Backend 窗口
echo ========================================
echo.
pause
