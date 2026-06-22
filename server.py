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

DB_DSN = "dbname=drop user=postgres password=postgres host=127.0.0.1 port=5433"
def get_db():
    return psycopg2.connect(DB_DSN)

mc = Minio("127.0.0.1:9000", access_key="drop", secret_key="drop1234", secure=False)
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
        threading.Thread(target=lambda: requests.post("http://localhost:5003/analyze/{}".format(tid), timeout=2)).start()
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
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=False)

@app.route('/api/tasks/<tid>/heatmap', methods=['GET'])
def get_heatmap(tid):
    try:
        import json
        data = mc.get_object("drop", f"tasks/{tid}/heatmap.json")
        content = data.read().decode('utf-8')
        data.close()
        return jsonify(json.loads(content))
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@app.route('/api/audit', methods=['GET'])
def get_audit():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 50")
    logs = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(logs)

@app.route('/api/audit', methods=['GET'])
def get_audit():
    conn = get_db()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 50")
    logs = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(logs)
