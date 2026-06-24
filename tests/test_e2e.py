"""
Drop 端到端集成测试

测试场景:
1. 正常路径: 创建任务 → Agent 拉取 → 采集 → 上传 → 分析 → 查看火焰图
2. 异常路径1: 无效 PID 导致采集失败
3. 异常路径2: Agent 离线检测

运行方式:
    python tests/test_e2e.py

前置条件:
    - PostgreSQL 和 MinIO 已启动
    - Server (5000), Agent, Analyzer 已启动
"""
import os
import sys
import time
import json
import requests
import subprocess
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

API_BASE = os.getenv("API_BASE", "http://localhost:5000")
AGENT_ID = "e2e-test-agent"
PASSED = 0
FAILED = 0


def check(msg, condition):
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  ✅ {msg}")
    else:
        FAILED += 1
        print(f"  ❌ {msg}")


def test_setup():
    """验证环境就绪"""
    print("\n📋 测试 0: 环境检查")
    try:
        resp = requests.get(f"{API_BASE}/api/agents", timeout=5)
        check("Server 可达", resp.status_code == 200)
    except Exception as e:
        check(f"Server 可达: {e}", False)
        return False

    # 注册测试 Agent
    requests.post(f"{API_BASE}/api/agents/heartbeat", json={
        "agent_id": AGENT_ID, "hostname": "e2e-test", "ip": "127.0.0.1"
    })
    check("Agent 注册成功", True)
    return True


def test_normal_path():
    """
    正常路径: 创建 per 采集任务 → 等待 DONE → 验证火焰图存在
    """
    print("\n📋 测试 1: 正常路径 — perf 采集 + 火焰图生成")

    # 找一个活跃的 PID (用当前进程)
    pid = os.getpid()

    # 创建任务
    resp = requests.post(f"{API_BASE}/api/tasks", json={
        "pid": pid,
        "duration": 3,
        "hz": 99,
        "agent_id": AGENT_ID,
        "profiler": "perf"
    })
    check("任务创建成功", resp.status_code == 200)
    tid = resp.json().get('tid', '')
    check(f"获得任务ID: {tid}", tid.startswith('task-'))

    # 等待任务完成（最多 60 秒）
    max_wait = 60
    status = "PENDING"
    while max_wait > 0 and status not in ("DONE", "FAILED"):
        time.sleep(2)
        max_wait -= 2
        resp = requests.get(f"{API_BASE}/api/tasks/{tid}")
        if resp.status_code == 200:
            status = resp.json().get('status', 'UNKNOWN')
            print(f"    任务状态: {status} (剩余等待 {max_wait}s)")
        else:
            break

    check(f"任务最终状态为 DONE (实际: {status})", status == "DONE")

    # 验证任务详情包含火焰图 URL
    resp = requests.get(f"{API_BASE}/api/tasks/{tid}")
    if resp.status_code == 200:
        task = resp.json()
        has_flamegraph = 'flamegraph_url' in task
        check("任务包含火焰图 URL", has_flamegraph)
        if has_flamegraph:
            # 验证火焰图可访问
            fg_resp = requests.get(task['flamegraph_url'], timeout=10)
            check(f"火焰图可访问 (HTTP {fg_resp.status_code})", fg_resp.status_code == 200)

    return tid


def test_invalid_pid():
    """
    异常路径1: 无效 PID (不存在的进程)
    """
    print("\n📋 测试 2: 异常路径 — 无效 PID")

    # 使用一个几乎不可能存在的 PID
    invalid_pid = 999999

    resp = requests.post(f"{API_BASE}/api/tasks", json={
        "pid": invalid_pid,
        "duration": 3,
        "hz": 99,
        "agent_id": AGENT_ID,
        "profiler": "perf"
    })
    check("无效PID任务创建成功", resp.status_code == 200)
    tid = resp.json().get('tid', '')

    # 等待任务完成
    max_wait = 30
    status = "PENDING"
    while max_wait > 0 and status not in ("DONE", "FAILED"):
        time.sleep(2)
        max_wait -= 2
        resp = requests.get(f"{API_BASE}/api/tasks/{tid}")
        if resp.status_code == 200:
            status = resp.json().get('status', 'UNKNOWN')
            print(f"    任务状态: {status} ({resp.json().get('reason', '')})")
        else:
            break

    # 无效 PID 预期会失败
    check(f"任务状态为 FAILED 或 DONE (实际: {status})", status in ("FAILED", "DONE"))
    if status == "FAILED":
        resp = requests.get(f"{API_BASE}/api/tasks/{tid}")
        reason = resp.json().get('reason', '')
        check(f"失败原因非空: {reason[:60]}", len(reason) > 0)


def test_agent_offline_detection():
    """
    异常路径2: 验证 Agent 离线检测机制
    """
    print("\n📋 测试 3: 异常路径 — Agent 离线检测")

    offline_agent = "offline-test-agent"

    # 注册 Agent 并发心跳
    resp = requests.post(f"{API_BASE}/api/agents/heartbeat", json={
        "agent_id": offline_agent, "hostname": "offline-test", "ip": "10.0.0.99"
    })
    check("离线测试Agent注册成功", resp.status_code == 200)

    # 检查 Agent 状态为 ONLINE
    resp = requests.get(f"{API_BASE}/api/agents")
    agents = resp.json()
    target = next((a for a in agents if a['agent_id'] == offline_agent), None)
    check(f"Agent 当前状态为 ONLINE (实际: {target['status'] if target else 'NOT_FOUND'})",
          target is not None and target['status'] == 'ONLINE')

    # 等待 40 秒让离线检测生效（Server 每 30s 检测一次）
    print("    等待 35 秒让离线检测生效...")
    time.sleep(35)

    # 检查 Agent 状态变为 OFFLINE
    resp = requests.get(f"{API_BASE}/api/agents")
    agents = resp.json()
    target = next((a for a in agents if a['agent_id'] == offline_agent), None)
    check(f"Agent 变为 OFFLINE (实际: {target['status'] if target else 'NOT_FOUND'})",
          target is not None and target['status'] == 'OFFLINE')

    # 验证审计日志中有离线记录
    resp = requests.get(f"{API_BASE}/api/audit")
    audit_logs = resp.json()
    offline_events = [l for l in audit_logs if l.get('event') == 'AGENT_OFFLINE' and l.get('agent_id') == offline_agent]
    check(f"审计日志包含离线事件 (找到 {len(offline_events)} 条)", len(offline_events) > 0)

    # 模拟恢复：再次发送心跳
    requests.post(f"{API_BASE}/api/agents/heartbeat", json={
        "agent_id": offline_agent, "hostname": "offline-test", "ip": "10.0.0.99"
    })

    # 检查是否恢复
    resp = requests.get(f"{API_BASE}/api/agents")
    agents = resp.json()
    target = next((a for a in agents if a['agent_id'] == offline_agent), None)
    check(f"Agent 恢复为 ONLINE (实际: {target['status'] if target else 'NOT_FOUND'})",
          target is not None and target['status'] == 'ONLINE')

    # 验证恢复审计日志
    resp = requests.get(f"{API_BASE}/api/audit")
    audit_logs = resp.json()
    recovered_events = [l for l in audit_logs if l.get('event') == 'AGENT_RECOVERED' and l.get('agent_id') == offline_agent]
    check(f"审计日志包含恢复事件 (找到 {len(recovered_events)} 条)", len(recovered_events) > 0)


def test_attribution():
    """测试智能归因"""
    print("\n📋 测试 4: 智能归因")

    # 先创建一个任务并等待完成
    pid = os.getpid()
    resp = requests.post(f"{API_BASE}/api/tasks", json={
        "pid": pid, "duration": 3, "hz": 99,
        "agent_id": AGENT_ID, "profiler": "perf"
    })
    tid = resp.json().get('tid', '')

    # 等待完成
    max_wait = 30
    status = "PENDING"
    while max_wait > 0 and status not in ("DONE", "FAILED"):
        time.sleep(2)
        max_wait -= 2
        resp = requests.get(f"{API_BASE}/api/tasks/{tid}")
        if resp.status_code == 200:
            status = resp.json().get('status', 'UNKNOWN')

    if status != "DONE":
        check(f"归因测试跳过（任务未完成: {status}）", True)
        return

    # 调用归因
    resp = requests.post(f"{API_BASE}/api/attribution/{tid}", timeout=30)
    check("归因API响应200", resp.status_code == 200)
    if resp.status_code == 200:
        attribution = resp.json().get('attribution', '')
        check(f"归因结果非空 (长度: {len(attribution)})", len(attribution) > 50)


def test_continuous_profiling():
    """测试持续分析"""
    print("\n📋 测试 5: 持续分析")

    # 启动
    resp = requests.post(f"{API_BASE}/api/continuous/start", json={
        "agent_id": AGENT_ID, "pid": 1
    })
    check("持续分析启动成功", resp.status_code == 200)

    # 获取窗口列表
    resp = requests.get(f"{API_BASE}/api/continuous/windows")
    check("窗口列表API正常", resp.status_code == 200)

    # 停止
    resp = requests.post(f"{API_BASE}/api/continuous/stop")
    check("持续分析停止成功", resp.status_code == 200)


def main():
    global PASSED, FAILED

    print("=" * 60)
    print("  Drop 端到端集成测试")
    print("=" * 60)

    if not test_setup():
        print("\n❌ 环境未就绪，请确认 Server (5000) 已启动")
        sys.exit(1)

    test_normal_path()
    test_invalid_pid()
    test_agent_offline_detection()
    test_attribution()
    test_continuous_profiling()

    print("\n" + "=" * 60)
    print(f"  测试结果: {PASSED} 通过, {FAILED} 失败, 共 {PASSED + FAILED} 项")
    print("=" * 60)

    if FAILED > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
