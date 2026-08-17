@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

rem ============================================================
rem  Patreon Downloader 图形界面一键启动脚本（Windows）
rem  双击本文件即可启动 GUI；可附带 --config <路径> 参数
rem  （注意：本文件为 UTF-8 编码，chcp 65001 必须位于首行附近，
rem    中文内容只能出现在 chcp 之后，否则会乱码）
rem ============================================================

rem 1) 优先使用已安装的 GUI 入口（uv sync / pip install -e . 后生成）
if exist ".venv\Scripts\patreon-dl-gui.exe" (
    start "" ".venv\Scripts\patreon-dl-gui.exe" %*
    exit /b 0
)

rem 2) 回退：直接用 venv 里的 Python 启动模块
if exist ".venv\Scripts\pythonw.exe" (
    echo [提示] 未找到 patreon-dl-gui 入口，改用 python -m 启动...
    start "" ".venv\Scripts\pythonw.exe" -m patreon_download.gui %*
    exit /b 0
)

rem 3) 回退：用 uv 同步依赖后启动
where uv >nul 2>nul
if %errorlevel%==0 (
    echo [提示] 未找到虚拟环境，正在用 uv 同步依赖并启动...
    uv sync
    if exist ".venv\Scripts\patreon-dl-gui.exe" (
        start "" ".venv\Scripts\patreon-dl-gui.exe" %*
        exit /b 0
    )
)

echo [错误] 启动失败：未找到 .venv 虚拟环境或 uv，请先执行 uv sync 安装依赖。
pause
exit /b 1
