#!/bin/bash
# Drop 开发模式一键启动脚本
# 用法: bash start_dev.sh
cd "$(dirname "$0")"
echo "========================================" 
echo "  🔥 Drop 性能分析平台"
echo "========================================"
[ ! -d "venv" ] && python3 -m venv venv && venv/bin/pip install -q -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
venv/bin/python dev_launcher.py
