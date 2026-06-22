import os,time,subprocess,tempfile,json,logging,collections,threading
from flask import Flask,request,jsonify
from minio import Minio
app=Flask(__name__)
logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
logger=logging.getLogger("analyzer")
mc=Minio("localhost:9000",access_key="drop",secret_key="drop1234",secure=False)
if not mc.bucket_exists("drop"): mc.make_bucket("drop")

def heatmap_json(folded):
    cnt=collections.Counter()
    with open(folded,'r') as f:
        for line in f:
            parts=line.strip().split()
            if len(parts)<2: continue
            count=int(parts[-1])
            stack=' '.join(parts[:-1])
            for func in stack.split(';'):
                func=func.strip()
                if func: cnt[func]+=count
    top=cnt.most_common(30)
    return [{"name":name,"value":val} for name,val in top]

def process(tid):
    logger.info(f"Analyzing {tid}")
    try:
        # 先检查是否为 eBPF 任务（存在 ebpf_folded.txt）
        try:
            mc.stat_object("drop", f"tasks/{tid}/ebpf_folded.txt")
            # eBPF 任务：直接使用折叠栈生成火焰图
            folded_local = f"/tmp/{tid}.ebpf.folded"
            mc.fget_object("drop", f"tasks/{tid}/ebpf_folded.txt", folded_local)
            with open(folded_local, 'r') as f:
                # 检查折叠栈是否为空
                if os.path.getsize(folded_local) == 0:
                    logger.error(f"empty ebpf folded for {tid}")
                    return
            # 生成火焰图
            svg = f"/tmp/{tid}.ebpf.svg"
            subprocess.run(f"flamegraph.pl {folded_local} > {svg}", shell=True, check=True)
            mc.fput_object("drop", f"tasks/{tid}/flamegraph.svg", svg)
            # 生成热力图
            hm = heatmap_json(folded_local)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
                json.dump(hm, f)
                f.flush()
                mc.fput_object("drop", f"tasks/{tid}/heatmap.json", f.name)
            logger.info(f"eBPF Task {tid} completed")
            return
        except Exception:
            # 不是 eBPF 任务，走原有 perf 流程
            pass
        
        # 原有 perf 流程
        local=f"/tmp/{tid}.perf.data"
        mc.fget_object("drop",f"tasks/{tid}/perf.data",local)
        with tempfile.TemporaryDirectory() as tmp:
            script=os.path.join(tmp,"perf.script")
            subprocess.run(f"perf script -i {local} --no-inline > {script} 2>/dev/null", shell=True, check=True)
            if os.path.getsize(script)==0: logger.error(f"empty script {tid}"); return
            folded=os.path.join(tmp,"folded.txt")
            subprocess.run(f"stackcollapse-perf.pl {script} > {folded}", shell=True, check=True)
            if os.path.getsize(folded)==0: logger.error(f"empty folded {tid}"); return
            svg=os.path.join(tmp,"flame.svg")
            subprocess.run(f"flamegraph.pl {folded} > {svg}", shell=True, check=True)
            mc.fput_object("drop",f"tasks/{tid}/flamegraph.svg",svg)
            hm=heatmap_json(folded)
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json') as f:
                json.dump(hm,f)
                f.flush()
                mc.fput_object("drop",f"tasks/{tid}/heatmap.json",f.name)
            logger.info(f"Task {tid} completed")
    except Exception as e: logger.error(f"Analyzer error {tid}: {e}")

@app.route('/analyze/<tid>', methods=['POST'])
def analyze(tid):
    threading.Thread(target=process, args=(tid,)).start()
    return jsonify({"status":"started","tid":tid})

if __name__=="__main__":
    app.run(host='0.0.0.0', port=5003, debug=False)
