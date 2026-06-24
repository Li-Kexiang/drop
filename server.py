import os, time, json, uuid, logging, threading, requests
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from minio import Minio

logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
app = Flask(__name__)
CORS(app)
logger = logging.getLogger("server")

# 数据库连接
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_NAME = os.getenv("DB_NAME", "drop")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "postgres")
DB_DSN = f"dbname={DB_NAME} user={DB_USER} password={DB_PASSWORD} host={DB_HOST} port={DB_PORT}"

# MinIO 连接
ANALYZER_URL = os.getenv("ANALYZER_URL", "http://localhost:5003")
def get_db():
    return psycopg2.connect(DB_DSN)

mc = Minio(MINIO_HOST, access_key="drop", secret_key="drop1234", secure=False)
if not mc.bucket_exists("drop"):
    mc.make_bucket("drop")

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            tid TEXT PRIMARY KEY,
            pid INTEGER,
            duration INTEGER,
            hz INTEGER,
            profiler TEXT,
            status TEXT DEFAULT 'PENDING',
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS agents (
            agent_id TEXT PRIMARY KEY,
            hostname TEXT,
            ip TEXT,
            last_heartbeat TIMESTAMP,
            status TEXT DEFAULT 'ONLINE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id SERIAL PRIMARY KEY,
            agent_id TEXT,
            event TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()
    logger.info("DB init")

init_db()

def audit(aid, evt, det=None):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO audit_log (agent_id, event, details) VALUES (%s, %s, %s)", (aid, evt, det))
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"Audit: {aid} - {evt}")

@app.route('/')
def index():
    return send_file('index2.html')

@app.route('/api/tasks', methods=['GET'])
def list_tasks():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM tasks ORDER BY created_at DESC")
    tasks = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(tasks)

@app.route('/api/agents/heartbeat', methods=['POST'])
def heartbeat():
    data = request.json
    aid = data.get('agent_id')
    if not aid:
        return jsonify({"error":"agent_id required"}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT status FROM agents WHERE agent_id=%s", (aid,))
    row = cur.fetchone()
    if row and row[0] == 'OFFLINE':
        audit(aid, "AGENT_RECOVERED", f"Agent {aid} recovered")
    cur.execute('''
        INSERT INTO agents (agent_id, hostname, ip, last_heartbeat, status)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP, 'ONLINE')
        ON CONFLICT (agent_id) DO UPDATE
        SET last_heartbeat = CURRENT_TIMESTAMP, status = 'ONLINE'
    ''', (aid, data.get('hostname',''), data.get('ip','')))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"status":"ok"})

@app.route('/api/agents', methods=['GET'])
def list_agents():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT agent_id, hostname, ip, last_heartbeat, status FROM agents ORDER BY created_at DESC")
    agents = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(agents)

@app.route('/api/tasks', methods=['POST'])
def create_task():
    data = request.json
    pid = data.get('pid')
    dur = data.get('duration', 5)
    hz = data.get('hz', 99)
    aid = data.get('agent_id')
    if not pid or not aid:
        return jsonify({"error":"pid and agent_id required"}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO agents (agent_id, hostname, ip, last_heartbeat, status)
        VALUES (%s, %s, %s, CURRENT_TIMESTAMP, 'ONLINE')
        ON CONFLICT DO NOTHING
    ''', (aid, 'unknown', 'unknown'))
    tid = "task-" + uuid.uuid4().hex[:8]
    cur.execute('''
        INSERT INTO tasks (tid, pid, duration, hz, profiler, status, reason, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'PENDING', 'Task created', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
    ''', (tid, pid, dur, hz, data.get('profiler', 'perf')))
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"Task created: {tid}")
    return jsonify({"tid": tid})

@app.route('/api/agents/<aid>/tasks/pending', methods=['GET'])
def get_pending(aid):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT tid, pid, duration, hz, profiler FROM tasks WHERE status='PENDING' ORDER BY created_at LIMIT 1")
    task = cur.fetchone()
    if task:
        cur.execute("UPDATE tasks SET status='RUNNING', reason='Agent picked up', updated_at=CURRENT_TIMESTAMP WHERE tid=%s", (task['tid'],))
        conn.commit()
    cur.close()
    conn.close()
    if task:
        return jsonify(task)
    else:
        return jsonify({}), 204

@app.route('/api/tasks/<tid>/result', methods=['POST'])
def task_result(tid):
    data = request.json
    status = data.get('status')
    reason = data.get('reason', '')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET status=%s, reason=%s, updated_at=CURRENT_TIMESTAMP WHERE tid=%s", (status, reason, tid))
    conn.commit()
    cur.close()
    conn.close()
    logger.info(f"Task {tid} status updated to {status}")
    if status == 'DONE':
        threading.Thread(target=lambda: requests.post(f"{ANALYZER_URL}/analyze/{tid}", timeout=2), daemon=True).start()
    return jsonify({"ok": True})

@app.route('/api/tasks/<tid>', methods=['GET'])
def get_task(tid):
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM tasks WHERE tid=%s", (tid,))
    task = cur.fetchone()
    cur.close()
    conn.close()
    if not task:
        return jsonify({"error":"not found"}), 404
    if task['status'] == 'DONE':
        try:
            tid = task['tid']
            task['flamegraph_url'] = f"http://localhost:9000/drop/tasks/{tid}/flamegraph.svg"
            task['heatmap_url'] = f"http://localhost:9000/drop/tasks/{tid}/heatmap.json"
        except Exception as e:
            logger.error(f"URL generation failed: {e}")
    return jsonify(task)

@app.route("/api/tasks/<tid>/heatmap", methods=["GET"])
def get_heatmap(tid):
    try:
        import json
        data = mc.get_object("drop", f"tasks/{tid}/heatmap.json")
        content = data.read().decode("utf-8")
        data.close()
        return jsonify(json.loads(content))
    except Exception as e:
        return jsonify({"error": str(e)}), 404

def check_offline():
    while True:
        conn = get_db()
        cur = conn.cursor()
        cur.execute('''
            UPDATE agents SET status='OFFLINE'
            WHERE last_heartbeat < CURRENT_TIMESTAMP - INTERVAL '30 seconds'
            AND status='ONLINE'
            RETURNING agent_id
        ''')
        off = cur.fetchall()
        for (aid,) in off:
            audit(aid, "AGENT_OFFLINE", f"Agent {aid} offline")
        conn.commit()
        cur.close()
        conn.close()
        time.sleep(10)

threading.Thread(target=check_offline, daemon=True).start()

@app.route("/api/audit", methods=["GET"])
def get_audit():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 50")
    logs = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(logs)

# ========== Continuous Profiling API ==========
_continuous_state = {"running": False, "pid": 1, "agent_id": None}

@app.route("/api/continuous/start", methods=["POST"])
def continuous_start():
    data = request.json
    _continuous_state["running"] = True
    _continuous_state["pid"] = data.get("pid", 1)
    _continuous_state["agent_id"] = data.get("agent_id")
    logger.info(f"Continuous profiling started for PID {_continuous_state['pid']}")
    return jsonify({"status": "ok", "message": f"Continuous profiling active for PID {_continuous_state['pid']}"})

@app.route("/api/continuous/stop", methods=["POST"])
def continuous_stop():
    _continuous_state["running"] = False
    logger.info("Continuous profiling stopped")
    return jsonify({"status": "ok", "message": "Continuous profiling stopped"})

@app.route("/api/continuous/windows", methods=["GET"])
def continuous_windows():
    """列出 continuous profiling 的时间窗口"""
    try:
        objects = mc.list_objects("drop", prefix="continuous/", recursive=True)
        windows = {}
        for obj in objects:
            parts = obj.object_name.split('/')
            if len(parts) >= 2:
                cid = parts[1]
                if cid not in windows:
                    try:
                        ts = int(cid.replace("continuous-", ""))
                    except ValueError:
                        ts = 0
                    windows[cid] = {"cid": cid, "ts": ts, "has_data": False}
                if "flamegraph.svg" in obj.object_name:
                    windows[cid]["has_data"] = True
        result = sorted(windows.values(), key=lambda x: x["ts"], reverse=True)[:20]
        return jsonify(result)
    except Exception as e:
        logger.error(f"List continuous windows error: {e}")
        return jsonify([])

# ========== 智能归因 API ==========
@app.route("/api/attribution/<tid>", methods=["POST"])
def attribution(tid):
    """
    智能归因：拉取火焰图数据 + 任务元信息，组合成 prompt 交给 LLM 分析。
    LLM 只能调用预定义工具，产出可验证的结论。
    """
    import json as _json

    try:
        # 获取任务元信息
        conn = get_db()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute("SELECT * FROM tasks WHERE tid=%s", (tid,))
        task = cur.fetchone()
        cur.close()
        conn.close()

        if not task:
            return jsonify({"error": "Task not found"}), 404

        # 获取热力图数据（函数采样计数）
        try:
            data = mc.get_object("drop", f"tasks/{tid}/heatmap.json")
            heatmap_data = _json.loads(data.read().decode("utf-8"))
            data.close()
        except Exception:
            heatmap_data = []

        # 构建归因 prompt
        top_functions = [f"{item['name']}: {item['value']} samples" for item in heatmap_data[:10]]
        func_summary = "\n".join(top_functions) if top_functions else "无法获取函数采样数据"

        prompt = f"""你是一位 Linux 性能优化专家。请分析以下性能采集数据并给出归因结论。

【采集元信息】
- 任务ID: {task['tid']}
- 目标PID: {task['pid']}
- 采集时长: {task['duration']}秒
- 采集器: {task.get('profiler', 'perf')}
- 采样率: {task.get('hz', 99)}Hz

【Top 函数采样计数】
{func_summary}

请按以下格式输出归因报告：
1. **热点识别**：哪些函数消耗了最多 CPU/IO 资源
2. **根因分析**：这些热点函数可能的根因
3. **优化建议**：具体可操作的优化方案（至少3条）
4. **置信度**：你对每条结论的置信度 (高/中/低)
5. **验证方法**：如何验证这些优化建议是否生效"""

        # 尝试调用 OpenAI-compatible API 进行归因
        attribution_text = _call_llm_attribution(prompt, heatmap_data)

        logger.info(f"Attribution completed for {tid}")
        return jsonify({"tid": tid, "attribution": attribution_text})

    except Exception as e:
        logger.error(f"Attribution error: {e}")
        return jsonify({"error": str(e)}), 500


def _call_llm_attribution(prompt, heatmap_data):
    """调用 LLM 进行智能归因，失败时回退到基于规则的归因"""
    llm_endpoint = os.getenv("LLM_ENDPOINT", "")
    llm_key = os.getenv("LLM_API_KEY", "")
    llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    if llm_endpoint and llm_key:
        try:
            resp = requests.post(
                llm_endpoint,
                headers={"Authorization": f"Bearer {llm_key}", "Content-Type": "application/json"},
                json={
                    "model": llm_model,
                    "messages": [
                        {"role": "system", "content": "你是一位 Linux 性能优化专家。请严格按用户要求的格式输出分析报告。只使用用户提供的数据进行分析，不要编造信息。"},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.3,
                    "max_tokens": 1500
                },
                timeout=60
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"]
            else:
                logger.warning(f"LLM API returned {resp.status_code}: {resp.text}")
        except Exception as e:
            logger.warning(f"LLM call failed: {e}")

    # 回退：基于规则的归因
    return _rule_based_attribution(heatmap_data)


def _rule_based_attribution(heatmap_data):
    """基于规则的智能归因（无需 LLM）"""
    if not heatmap_data:
        return """## 智能归因报告（基于规则）

**热点识别**：未获取到足够的采样数据。

**根因分析**：采样数据为空，可能原因：
- 目标进程在采样期间无活动
- perf 权限不足（请检查 perf_event_paranoid 设置）
- 采样时长过短

**优化建议**：
1. 确认目标 PID 在采样期间有足够的 CPU 活动
2. 执行 `sudo sysctl -w kernel.perf_event_paranoid=0` 放宽权限
3. 增加采样时长至 10-15 秒以获得更多样本

**置信度**：低（数据不足）
**验证方法**：重新采样后对比火焰图"""

    top3 = heatmap_data[:3]
    total = sum(item['value'] for item in heatmap_data)

    report = "## 智能归因报告（基于规则）\n\n"
    report += "### 1. 热点识别\n"
    for item in top3:
        pct = (item['value'] / total * 100) if total > 0 else 0
        report += f"- **{item['name']}**: {item['value']} samples ({pct:.1f}%)\n"

    report += "\n### 2. 根因分析\n"
    # 基于函数名模式给出启发式分析
    for item in top3:
        name_lower = item['name'].lower()
        if any(kw in name_lower for kw in ['malloc', 'free', 'alloc', 'mmap']):
            report += f"- `{item['name']}`: 内存分配热点，可能因频繁分配/释放导致。建议使用内存池或对象复用。\n"
        elif any(kw in name_lower for kw in ['read', 'write', 'io', 'disk', 'vfs']):
            report += f"- `{item['name']}`: IO 热点，可能因频繁磁盘读写。建议使用缓存或异步 IO。\n"
        elif any(kw in name_lower for kw in ['lock', 'mutex', 'spin', 'sem']):
            report += f"- `{item['name']}`: 锁竞争热点，可能因锁粒度过大。建议减少临界区或使用无锁结构。\n"
        elif any(kw in name_lower for kw in ['json', 'parse', 'serial', 'encode', 'decode']):
            report += f"- `{item['name']}`: 序列化/解析热点。建议使用更高效的序列化库或缓存解析结果。\n"
        else:
            report += f"- `{item['name']}`: 高采样函数，建议检查是否存在不必要的重复调用或算法复杂度问题。\n"

    report += "\n### 3. 优化建议\n"
    report += "1. 检查热点函数的调用频率和调用链，确认是否存在冗余调用\n"
    report += "2. 使用 perf annotate 对热点函数进行指令级分析\n"
    report += "3. 考虑使用更高效的数据结构或算法替代当前实现\n"
    report += "4. 如果热点在内核空间，检查系统调用是否可批量化\n"

    report += "\n### 4. 置信度\n"
    report += "- 热点识别: 高（基于采样数据直接统计）\n"
    report += "- 根因分析: 中（仅基于函数名模式匹配，需人工确认）\n"
    report += "- 优化建议: 中（通用建议，具体场景需调整）\n"

    report += "\n### 5. 验证方法\n"
    report += "1. 实施优化后重新采样，对比火焰图变化\n"
    report += "2. 使用 `perf stat` 对比优化前后的 IPC、cache-miss 等指标\n"
    report += "3. 在相同负载下对比响应时间和吞吐量\n"

    return report


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)
