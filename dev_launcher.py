"""
Drop 开发模式启动脚本 (无需 Docker/PostgreSQL/MinIO)
使用 SQLite + 本地文件存储

启动方式:
    python dev_launcher.py

或:
    set DEV_MODE=true && python dev_launcher.py
"""
import os
import sys
import time
import subprocess
import threading

# 设置开发模式环境变量
os.environ["DEV_MODE"] = "true"
os.environ["SQLITE_PATH"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "drop_dev.db")
os.environ["LOCAL_STORAGE"] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_storage")

# 创建存储目录
storage_dir = os.environ["LOCAL_STORAGE"]
os.makedirs(storage_dir, exist_ok=True)
os.makedirs(os.path.join(storage_dir, "tasks"), exist_ok=True)
os.makedirs(os.path.join(storage_dir, "continuous"), exist_ok=True)

print("=" * 50)
print("  Drop 开发模式启动")
print(f"  数据库: SQLite ({os.environ['SQLITE_PATH']})")
print(f"  存储: 本地文件 ({storage_dir})")
print("=" * 50)


def run_module(module_name):
    """运行一个 Python 模块"""
    proc = subprocess.Popen(
        [sys.executable, module_name],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        env=os.environ.copy()
    )
    return proc


print("\n启动 Server (port 5000)...")
server_proc = run_module("server.py")
time.sleep(2)

print("启动 Analyzer (port 5003)...")
analyzer_proc = run_module("analyzer.py")
time.sleep(1)

print("启动 Agent...")
agent_proc = run_module("agent.py")
time.sleep(2)

print("\n" + "=" * 50)
print("  ✅ Drop 开发模式启动完成!")
print("  🌐 Web UI: http://localhost:5000")
print("  📊 Analyzer: http://localhost:5003")
print("=" * 50)
print("\n按 Ctrl+C 停止所有服务...\n")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n正在停止服务...")
    for proc in [agent_proc, analyzer_proc, server_proc]:
        proc.terminate()
    for proc in [agent_proc, analyzer_proc, server_proc]:
        proc.wait(timeout=5)
    print("所有服务已停止。")
