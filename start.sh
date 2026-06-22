#!/bin/bash
echo "===== 启动 Drop 多进程版 ====="

# 停止旧进程
pkill -f "python.*server.py" 2>/dev/null
pkill -f "python.*agent.py" 2>/dev/null
pkill -f "python.*analyzer.py" 2>/dev/null

# 启动 Server（端口 5000）
nohup python3 server.py > /tmp/server.log 2>&1 &
sleep 2

# 启动 Agent（端口无，向 Server 心跳）
nohup python3 agent.py > /tmp/agent.log 2>&1 &
sleep 2

# 启动 Analyzer（端口 5002）
nohup python3 analyzer.py > /tmp/analyzer.log 2>&1 &
sleep 2

# 启动简单 Web 服务（端口 8080）提供 index.html
nohup python3 -m http.server 8080 --directory . > /tmp/web.log 2>&1 &

echo "===== 启动完成 ====="
echo "Server:   http://localhost:5000"
echo "Analyzer: http://localhost:5002"
echo "Web UI:   http://localhost:8080 (访问这个)"
echo "查看日志: tail -f /tmp/server.log"
