#!/bin/bash
# Drop 开发模式一键启动 (Ubuntu)
# 自带 venv 创建、依赖安装，自动选择正确的 Python

set -e
cd "$(dirname "$0")"

echo "========================================="
echo "  Drop 开发模式启动"
echo "========================================="

# 1. 创建 venv
if [ ! -f venv/bin/python3 ]; then
    echo "创建虚拟环境..."
    python3 -m venv venv
    echo "安装依赖..."
    venv/bin/pip install -q -r requirements.txt
fi

# 2. 设置环境变量
export DEV_MODE=true
export SQLITE_PATH="$(pwd)/drop_dev.db"
export LOCAL_STORAGE="$(pwd)/data_storage"
mkdir -p "$LOCAL_STORAGE/tasks" "$LOCAL_STORAGE/continuous"

# 3. 停旧进程
pkill -f "python.*server.py" 2>/dev/null || true
pkill -f "python.*agent.py" 2>/dev/null || true
pkill -f "python.*analyzer.py" 2>/dev/null || true
sleep 1

# 4. 用 venv 的 Python 启动所有服务
echo ""
echo "启动 Server (5000)..."
venv/bin/python3 server.py &
sleep 2

echo "启动 Analyzer (5003)..."
venv/bin/python3 analyzer.py &
sleep 1

echo "启动 Agent..."
venv/bin/python3 agent.py &
sleep 2

echo ""
echo "========================================="
echo "  ✅ 全部启动完成!"
echo "  🌐 http://localhost:5000"
echo "========================================="
echo ""
echo "按 Ctrl+C 停止所有服务"

trap "echo '停止中...'; kill 0" EXIT
wait
