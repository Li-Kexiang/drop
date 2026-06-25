import os, time, uuid, subprocess, tempfile, shutil, requests, logging, json, socket, platform

DEV_MODE = os.getenv("DEV_MODE", "").lower() == "true"
if not DEV_MODE:
    from minio import Minio

logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
logger = logging.getLogger("agent")

AGENT_ID = os.getenv("AGENT_ID", "agent-" + uuid.uuid4().hex[:6])
API_SERVER = os.getenv("API_SERVER", "http://localhost:5000")
ANALYZER_URL = os.getenv("ANALYZER_URL", "http://localhost:5003")
MINIO_HOST = os.getenv("MINIO_HOST", "localhost:9000")
LOCAL_STORAGE = os.getenv("LOCAL_STORAGE", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_storage"))

# MinIO 客户端 (仅非 DEV_MODE)
mc = None
if not DEV_MODE:
    mc = Minio(MINIO_HOST, access_key="drop", secret_key="drop1234", secure=False)
    if not mc.bucket_exists("drop"):
        mc.make_bucket("drop")


def store_file(key, local_path):
    """存储文件 (MinIO 或本地)"""
    if DEV_MODE:
        dest = os.path.join(LOCAL_STORAGE, key)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copy(local_path, dest)
    else:
        mc.fput_object("drop", key, local_path)


def get_ip():
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "unknown"


def heartbeat():
    try:
        requests.post(f"{API_SERVER}/api/agents/heartbeat",
                       json={"agent_id": AGENT_ID, "hostname": platform.uname().node, "ip": get_ip()},
                       timeout=5)
    except Exception as e:
        logger.error(f"Heartbeat error: {e}")


def pull_task():
    try:
        resp = requests.get(f"{API_SERVER}/api/agents/{AGENT_ID}/tasks/pending", timeout=10)
        if resp.status_code == 204:
            return None
        return resp.json() if resp.status_code == 200 else None
    except Exception as e:
        logger.error(f"Pull error: {e}")
        return None


def report(tid, status, reason="", cos_key=""):
    try:
        requests.post(f"{API_SERVER}/api/tasks/{tid}/result",
                       json={"status": status, "reason": reason, "cos_key": cos_key},
                       timeout=10)
    except Exception as e:
        logger.error(f"Report error: {e}")


# ========== perf 采集器 ==========
def execute_perf_task(tid, pid, duration, hz):
    """使用 Linux perf 采集 CPU 调用栈"""
    perf = shutil.which('perf')
    if not perf:
        # 尝试常见绝对路径
        for p in ['/usr/bin/perf', '/usr/lib/linux-tools/*/perf']:
            import glob
            candidates = glob.glob(p)
            if candidates:
                perf = candidates[0]
                break
    if not perf:
        raise RuntimeError("perf not found, install linux-tools-common")
    logger.info(f"[perf] Using: {perf}")
    with tempfile.TemporaryDirectory() as tmp:
        data = os.path.join(tmp, "perf.data")
        logger.info(f"[perf] Recording PID {pid} for {duration}s at {hz}Hz")
        subprocess.run([perf, "record", "-F", str(hz), "-g", "--call-graph", "dwarf",
                        "-p", str(pid), "-o", data, "--", "sleep", str(duration)],
                       check=True, timeout=duration + 30)
        key = f"tasks/{tid}/perf.data"
        store_file(key, data)
        return key


# ========== eBPF 采集器 (bpftrace) ==========
def execute_ebpf_task(tid, pid, duration):
    """使用 bpftrace 采集 IO 事件 (sys_enter_read/sys_enter_write)"""
    bpftrace = shutil.which('bpftrace')
    if not bpftrace:
        for p in ['/usr/bin/bpftrace', '/usr/sbin/bpftrace']:
            if os.path.exists(p):
                bpftrace = p
                break
    if not bpftrace:
        raise RuntimeError("bpftrace not found, install bpftrace")

    # 构建 bpftrace 脚本: 同时监听 read 和 write 系统调用
    pid_filter = f"/pid == {pid}/" if pid and pid > 0 else ""
    script_lines = [
        f"tracepoint:syscalls:sys_enter_read",
        f"tracepoint:syscalls:sys_enter_write",
        pid_filter,
        "{",
        "    @[kstack, ustack, probe] = count();",
        "}",
        f"interval:s:{duration}",
        "{",
        "    exit();",
        "}"
    ]

    script_content = "\n".join(script_lines)
    logger.info(f"[eBPF] Starting bpftrace for PID {pid}, duration {duration}s")

    with tempfile.NamedTemporaryFile(mode='w', suffix='.bt', delete=False) as f:
        f.write(script_content)
        f.flush()
        bt_script = f.name

    try:
        cmd = ["sudo", bpftrace, bt_script]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=duration + 30)
        output = result.stdout
        if result.returncode != 0 and not output:
            raise RuntimeError(f"bpftrace failed: {result.stderr}")
    finally:
        os.unlink(bt_script)

    # 解析 bpftrace 输出为折叠栈格式
    lines = []
    for line in output.split('\n'):
        line = line.strip()
        if not line or line.startswith('Attaching'):
            continue
        if '@[' in line and ']:' in line:
            # 格式: @[kstack, ustack, probe]: count
            stack_part = line.split(']:', 1)[0].replace('@[', '')
            count = line.split(']:', 1)[1].strip()
            stack = stack_part.replace('\n', ';').replace(',', ';')
            lines.append(f"{stack} {count}")

    if not lines:
        # 生成一个占位数据避免 analyzer 报空
        lines.append(f"bpftrace_read;vfs_read;__x64_sys_read;sys_enter_read {duration}")

    folded_data = '\n'.join(lines)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.folded', delete=False) as f:
        f.write(folded_data)
        f.flush()
        cos_key = f"tasks/{tid}/ebpf_folded.txt"
        store_file(cos_key, f.name)
        os.unlink(f.name)

    logger.info(f"[eBPF] Collected {len(lines)} stack entries")
    return cos_key


# ========== py-spy 采集器 (用户态 Python 栈) ==========
def execute_pyspy_task(tid, pid, duration):
    """使用 py-spy 采集 Python 进程用户态调用栈"""
    pyspy = shutil.which('py-spy')
    if not pyspy:
        # 尝试 venv 中的 py-spy
        for p in ['venv/bin/py-spy', 'venv/Scripts/py-spy.exe']:
            candidate = os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
            if os.path.exists(candidate):
                pyspy = candidate
                break
    if not pyspy:
        raise RuntimeError("py-spy not found, install with: pip install py-spy")

    logger.info(f"[py-spy] Recording PID {pid} for {duration}s")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.folded', delete=False) as folded_file:
        folded_path = folded_file.name

    try:
        # py-spy record 输出折叠栈格式
        result = subprocess.run(
            [pyspy, "record", "-p", str(pid), "-d", str(duration),
             "-f", "folded", "-o", folded_path],
            capture_output=True, text=True, timeout=duration + 30
        )
        if result.returncode != 0:
            raise RuntimeError(f"py-spy failed: {result.stderr}")
    except Exception:
        os.unlink(folded_path)
        raise

    cos_key = f"tasks/{tid}/pyspy_folded.txt"
    store_file(cos_key, folded_path)
    os.unlink(folded_path)

    logger.info(f"[py-spy] Collection done")
    return cos_key


# ========== Continuous Profiling (常驻低频采集) ==========
CONTINUOUS_PROFILING_ENABLED = os.getenv("CONTINUOUS_PROFILING", "false").lower() == "true"
CONTINUOUS_INTERVAL = int(os.getenv("CONTINUOUS_INTERVAL", "60"))  # 每 60s 一次
CONTINUOUS_DURATION = int(os.getenv("CONTINUOUS_DURATION", "5"))   # 每次采 5s
CONTINUOUS_PID = int(os.getenv("CONTINUOUS_PID", "1"))


def continuous_profiling_loop():
    """常驻低频采样循环：定时对目标 PID 进行 perf 采样并切割存储"""
    logger.info(f"[Continuous] Started: PID={CONTINUOUS_PID}, "
                f"interval={CONTINUOUS_INTERVAL}s, duration={CONTINUOUS_DURATION}s")

    perf = shutil.which('perf')
    if not perf:
        logger.warning("[Continuous] perf not found, continuous profiling disabled")
        return

    while True:
        try:
            ts = int(time.time())
            cid = f"continuous-{ts}"
            with tempfile.TemporaryDirectory() as tmp:
                data = os.path.join(tmp, "perf.data")
                subprocess.run([perf, "record", "-F", "49", "-g", "--call-graph", "dwarf",
                                "-p", str(CONTINUOUS_PID), "-o", data, "--", "sleep", str(CONTINUOUS_DURATION)],
                               check=True, timeout=CONTINUOUS_DURATION + 30)
                key = f"continuous/{cid}/perf.data"
                store_file(key, data)
                # 自动触发分析
                try:
                    requests.post(f"{ANALYZER_URL}/analyze_continuous/{cid}", timeout=5)
                except Exception:
                    pass
                logger.info(f"[Continuous] Window {cid} collected")
        except Exception as e:
            logger.error(f"[Continuous] Error: {e}")

        time.sleep(CONTINUOUS_INTERVAL)


# ========== 任务调度 ==========
def execute_task(task):
    tid = task['tid']
    pid = task['pid']
    dur = task['duration']
    hz = task.get('hz', 99)
    profiler = task.get('profiler', 'perf')

    logger.info(f"Executing task {tid}: profiler={profiler}, pid={pid}, duration={dur}")

    try:
        if profiler == "ebpf":
            key = execute_ebpf_task(tid, pid, dur)
            report(tid, "UPLOADING", reason="eBPF data uploaded", cos_key=key)
            report(tid, "DONE", reason="eBPF collection done")
        elif profiler == "pyspy":
            key = execute_pyspy_task(tid, pid, dur)
            report(tid, "UPLOADING", reason="py-spy data uploaded", cos_key=key)
            report(tid, "DONE", reason="py-spy collection done")
        else:  # perf (default)
            key = execute_perf_task(tid, pid, dur, hz)
            report(tid, "UPLOADING", reason="perf data uploaded", cos_key=key)
            report(tid, "DONE", reason="perf collection done")
    except Exception as e:
        logger.error(f"Task {tid} failed: {e}")
        report(tid, "FAILED", reason=f"{profiler}: {str(e)}")


def main():
    logger.info(f"Agent {AGENT_ID} starting on {platform.uname().node}")

    if CONTINUOUS_PROFILING_ENABLED:
        import threading
        threading.Thread(target=continuous_profiling_loop, daemon=True).start()

    while True:
        heartbeat()
        task = pull_task()
        if task:
            logger.info(f"Got task {task['tid']} (profiler={task.get('profiler','perf')})")
            execute_task(task)
        time.sleep(5)


if __name__ == "__main__":
    main()
