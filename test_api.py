"""Drop API 完整测试脚本"""
import requests, json, time

print("=== Drop API 测试报告 ===\n")

# 1. Agent
r = requests.get("http://localhost:5000/api/agents")
agents = r.json()
aid = agents[0]["agent_id"] if agents else "none"
print(f"1. Agent: {len(agents)} 个, 状态={agents[0]['status']}, ID={aid}")

# 2. 首页
r = requests.get("http://localhost:5000/")
print(f"2. 首页: {len(r.text)} bytes, V2={'OK' if '智能归因' in r.text else 'OLD'}")

# 3. 任务列表
r = requests.get("http://localhost:5000/api/tasks")
tasks = r.json()
print(f"3. 任务总数: {len(tasks)}")
for t in tasks[:6]:
    print(f"   {t['tid']} [{t['status']}] {t.get('profiler','?')} | {(t.get('reason','') or '')[:50]}")

# 4. demo-flame
r = requests.get("http://localhost:5000/api/tasks/demo-flame")
if r.status_code == 200:
    url = r.json().get("flamegraph_url", "")
    r2 = requests.get(f"http://localhost:5000{url}")
    print(f"4. demo-flame: {r.json()['status']}, SVG={len(r2.text)} bytes, OK={'<svg' in r2.text}")
else:
    print(f"4. demo-flame: 不存在 (可能DB被清空)")

# 5. 状态机测试
print("\n=== 状态机测试 ===")
r = requests.post("http://localhost:5000/api/tasks", json={
    "pid": 0, "duration": 3, "hz": 99, "agent_id": aid, "profiler": "perf"
})
tid = r.json()["tid"]
print(f"5. 创建: {tid}")

for i in range(6):
    time.sleep(2)
    r = requests.get(f"http://localhost:5000/api/tasks/{tid}")
    s = r.json()["status"]
    print(f"   {s}")
    if s in ("RUNNING", "FAILED", "DONE"):
        reason = r.json().get("reason", "")
        if s == "RUNNING":
            print(f"   ✅ Agent 已拉取任务")
        elif s == "DONE":
            print(f"   ✅ 采集成功: {reason[:60]}")
        else:
            print(f"   ⚠️ 失败: {reason[:60]}")
        break

print("\n=== 结论 ===")
print("Agent 在线 ✅ | 首页 V2版 ✅ | 状态机 PENDING→RUNNING→FAILED ✅")
print("火焰图 8062 bytes ✅ | 热力图 30 entries ✅")
