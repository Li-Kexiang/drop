import os,time,uuid,subprocess,tempfile,shutil,requests,logging
from minio import Minio
logging.basicConfig(level=logging.INFO, format='{"time":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}')
logger=logging.getLogger("agent")
AGENT_ID=os.getenv("AGENT_ID","agent-abc123")
API_SERVER=os.getenv("API_SERVER","http://localhost:5000")
mc=Minio("localhost:9000",access_key="drop",secret_key="drop1234",secure=False)
if not mc.bucket_exists("drop"): mc.make_bucket("drop")

def heartbeat():
    try:
        requests.post(f"{API_SERVER}/api/agents/heartbeat", json={"agent_id":AGENT_ID,"hostname":os.uname().nodename,"ip":"unknown"}, timeout=5)
    except Exception as e: logger.error(f"Heartbeat error: {e}")

def pull_task():
    try:
        resp=requests.get(f"{API_SERVER}/api/agents/{AGENT_ID}/tasks/pending", timeout=10)
        if resp.status_code==204: return None
        return resp.json() if resp.status_code==200 else None
    except Exception as e: logger.error(f"Pull error: {e}"); return None

def report(tid,status,reason="",cos_key=""):
    try:
        requests.post(f"{API_SERVER}/api/tasks/{tid}/result", json={"status":status,"reason":reason,"cos_key":cos_key}, timeout=10)
    except Exception as e: logger.error(f"Report error: {e}")

def execute_task(task):
    profiler = "perf"
    profiler = task.get("profiler", "perf")
    profiler = "perf"
    tid=task['tid']; pid=task['pid']; dur=task['duration']; hz=task['hz']
    try:
        perf=shutil.which('perf')
        if not perf: raise RuntimeError("perf not found")
        with tempfile.TemporaryDirectory() as tmp:
            data=os.path.join(tmp,"perf.data")
            logger.info(f"Recording PID {pid} for {dur}s")
            subprocess.run([perf,"record","-F",str(hz),"-g","--call-graph","dwarf","-p",str(pid),"-o",data,"--","sleep",str(dur)], check=True)
            key=f"tasks/{tid}/perf.data"
            mc.fput_object("drop",key,data)
            report(tid,"UPLOADING",reason="Raw data uploaded",cos_key=key)
            report(tid,"DONE",reason="Collection done")
    except Exception as e:
        logger.error(f"Task {tid} failed: {e}")
        report(tid,"FAILED",reason=str(e))

def main():
    logger.info(f"Agent {AGENT_ID} starting")
    while True:
        heartbeat()
        task=pull_task()
        if task:
            logger.info(f"Got task {task['tid']}")
            execute_task(task)
        time.sleep(5)
if __name__=="__main__": main()
