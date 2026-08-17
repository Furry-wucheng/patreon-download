#!/usr/bin/env sh
# ============================================================
#  Patreon Downloader 图形界面一键启动脚本（Linux / macOS）
#  用法：./start-gui.sh [--config <路径>]
# ============================================================
cd "$(dirname "$0")" || exit 1

# 1) 优先使用已安装的 GUI 入口（uv sync / pip install -e . 后生成）
if [ -x ".venv/bin/patreon-dl-gui" ]; then
    exec .venv/bin/patreon-dl-gui "$@"
fi

# 2) 回退：直接用 venv 里的 Python 启动模块
if [ -x ".venv/bin/python" ]; then
    echo "[提示] 未找到 patreon-dl-gui 入口，改用 python -m 启动..."
    exec .venv/bin/python -m patreon_download.gui "$@"
fi

# 3) 回退：用 uv 同步依赖后启动
if command -v uv >/dev/null 2>&1; then
    echo "[提示] 未找到虚拟环境，正在用 uv 同步依赖并启动..."
    uv sync
    if [ -x ".venv/bin/patreon-dl-gui" ]; then
        exec .venv/bin/patreon-dl-gui "$@"
    fi
fi

echo "[错误] 启动失败：未找到 .venv 虚拟环境或 uv，请先执行 uv sync 安装依赖。" >&2
exit 1
