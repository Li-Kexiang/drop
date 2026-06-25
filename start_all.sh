#!/bin/bash
# Drop 完整启动脚本 - 含 Cloudflare 隧道
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=========================================="
echo "  🔥 Drop 性能分析平台"
echo "=========================================="

# 确保 venv 存在
if [ ! -d "venv" ]; then
    echo "[1/4] 创建虚拟环境..."
    python3 -m venv venv
    venv/bin/pip install -q -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
fi

# 下载 cloudflared（如果不存在）
if [ ! -f "/tmp/cloudflared" ]; then
    echo "[2/4] 下载 Cloudflare Tunnel..."
    curl -sL -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
    chmod +x /tmp/cloudflared
fi

# 启动 Drop 服务
echo "[3/4] 启动 Drop 服务 (Server + Analyzer + Agent)..."
venv/bin/python dev_launcher.py &
DEV_PID=$!
sleep 4

# 启动 Cloudflare 隧道
echo "[4/4] 启动公网隧道..."
/tmp/cloudflared tunnel --url http://localhost:5000 2>&1 | while IFS= read -r line; do
    echo "$line"
    if echo "$line" | grep -q 'trycloudflare.com'; then
        URL=$(echo "$line" | grep -o 'https://[^ ]*trycloudflare\.com')
        echo ""
        echo "=========================================="
        echo "  ✅ 公网访问地址:"
        echo "  👉 $URL"
        echo "=========================================="
        echo ""
    fi
done &
CF_PID=$!

echo ""
echo "本地访问: http://localhost:5000"
echo "按 Ctrl+C 停止所有服务"
echo ""

trap "kill $DEV_PID $CF_PID 2>/dev/null; echo '已停止'" EXIT
wait
