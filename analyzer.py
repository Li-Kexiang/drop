import os, time, subprocess, tempfile, json, logging, collections, threading, shutil
from flask import Flask, request, jsonify
from minio import Minio

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
logger = logging.getLogger("analyzer")

MINIO_HOST = os.getenv("MINIO_HOST", "localhost:9000")
mc = Minio(MINIO_HOST, access_key="drop", secret_key="drop1234", secure=False)
if not mc.bucket_exists("drop"):
    mc.make_bucket("drop")


def heatmap_json(folded_path):
    """从折叠栈文件生成热力图数据 (Top 30 函数)"""
    cnt = collections.Counter()
    with open(folded_path, 'r') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            count = int(parts[-1])
            stack = ' '.join(parts[:-1])
            for func in stack.split(';'):
                func = func.strip()
                if func:
                    cnt[func] += count
    top = cnt.most_common(30)
    return [{"name": name, "value": val} for name, val in top]


def generate_flamegraph(folded_path, svg_path):
    """使用 flamegraph.pl 生成火焰图 SVG"""
    flamegraph = shutil.which('flamegraph.pl')
    if not flamegraph:
        # 尝试从 PATH 或常见位置查找
        for candidate in ['flamegraph.pl', '/usr/local/bin/flamegraph.pl',
                          '/opt/FlameGraph/flamegraph.pl']:
            if os.path.exists(candidate):
                flamegraph = candidate
                break
    if not flamegraph:
        raise RuntimeError("flamegraph.pl not found")

    with open(folded_path, 'r') as inf, open(svg_path, 'w') as outf:
        subprocess.run([flamegraph], stdin=inf, stdout=outf, check=True)


def upload_artifacts(tid, folded_path, prefix="tasks"):
    """上传火焰图和热力图到 MinIO"""
    svg_path = folded_path + ".svg"
    generate_flamegraph(folded_path, svg_path)
    mc.fput_object("drop", f"{prefix}/{tid}/flamegraph.svg", svg_path)

    hm = heatmap_json(folded_path)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(hm, f)
        f.flush()
        mc.fput_object("drop", f"{prefix}/{tid}/heatmap.json", f.name)
        os.unlink(f.name)

    os.unlink(svg_path)
    logger.info(f"Artifacts uploaded for {tid}")


def process_perf(tid):
    """处理 perf 采集数据"""
    local = f"/tmp/{tid}.perf.data"
    mc.fget_object("drop", f"tasks/{tid}/perf.data", local)

    with tempfile.TemporaryDirectory() as tmp:
        script = os.path.join(tmp, "perf.script")
        subprocess.run(f"perf script -i {local} --no-inline > {script} 2>/dev/null",
                       shell=True, check=True)
        if os.path.getsize(script) == 0:
            raise RuntimeError("perf script output empty")

        folded = os.path.join(tmp, "folded.txt")
        subprocess.run(f"stackcollapse-perf.pl {script} > {folded}",
                       shell=True, check=True)
        if os.path.getsize(folded) == 0:
            raise RuntimeError("folded stack empty")

        upload_artifacts(tid, folded, "tasks")
    os.unlink(local)


def process_ebpf(tid):
    """处理 eBPF 采集数据 (已经是折叠栈格式)"""
    folded_local = f"/tmp/{tid}.ebpf.folded"
    mc.fget_object("drop", f"tasks/{tid}/ebpf_folded.txt", folded_local)

    if os.path.getsize(folded_local) == 0:
        raise RuntimeError("empty ebpf folded data")

    upload_artifacts(tid, folded_local, "tasks")
    os.unlink(folded_local)


def process_pyspy(tid):
    """处理 py-spy 采集数据 (已经是折叠栈格式)"""
    folded_local = f"/tmp/{tid}.pyspy.folded"
    mc.fget_object("drop", f"tasks/{tid}/pyspy_folded.txt", folded_local)

    if os.path.getsize(folded_local) == 0:
        raise RuntimeError("empty py-spy folded data")

    upload_artifacts(tid, folded_local, "tasks")
    os.unlink(folded_local)


def process(tid):
    """自动检测数据类型并处理"""
    logger.info(f"Analyzing {tid}")
    try:
        # 检测数据类型
        try:
            mc.stat_object("drop", f"tasks/{tid}/ebpf_folded.txt")
            logger.info(f"Detected eBPF data for {tid}")
            process_ebpf(tid)
            return
        except Exception:
            pass

        try:
            mc.stat_object("drop", f"tasks/{tid}/pyspy_folded.txt")
            logger.info(f"Detected py-spy data for {tid}")
            process_pyspy(tid)
            return
        except Exception:
            pass

        try:
            mc.stat_object("drop", f"tasks/{tid}/perf.data")
            logger.info(f"Detected perf data for {tid}")
            process_perf(tid)
            return
        except Exception:
            pass

        raise RuntimeError(f"No data found for task {tid}")

    except Exception as e:
        logger.error(f"Analyzer error {tid}: {e}")


def process_continuous(cid):
    """处理 Continuous Profiling 数据"""
    logger.info(f"Analyzing continuous window {cid}")
    try:
        local = f"/tmp/{cid}.perf.data"
        mc.fget_object("drop", f"continuous/{cid}/perf.data", local)

        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "perf.script")
            subprocess.run(f"perf script -i {local} --no-inline > {script} 2>/dev/null",
                           shell=True, check=True)
            if os.path.getsize(script) == 0:
                logger.warning(f"Empty continuous script for {cid}")
                return

            folded = os.path.join(tmp, "folded.txt")
            subprocess.run(f"stackcollapse-perf.pl {script} > {folded}",
                           shell=True, check=True)
            if os.path.getsize(folded) == 0:
                logger.warning(f"Empty continuous folded for {cid}")
                return

            upload_artifacts(cid, folded, "continuous")
        os.unlink(local)
        logger.info(f"Continuous window {cid} completed")
    except Exception as e:
        logger.error(f"Continuous analyzer error {cid}: {e}")


@app.route('/analyze/<tid>', methods=['POST'])
def analyze(tid):
    threading.Thread(target=process, args=(tid,), daemon=True).start()
    return jsonify({"status": "started", "tid": tid})


@app.route('/analyze_continuous/<cid>', methods=['POST'])
def analyze_continuous(cid):
    threading.Thread(target=process_continuous, args=(cid,), daemon=True).start()
    return jsonify({"status": "started", "cid": cid})


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5003, debug=False)
