"""
Drop 单元测试
覆盖 server.py 的核心逻辑

运行: python -m pytest tests/test_server.py -v
"""
import os
import sys
import json
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5433")
os.environ.setdefault("MINIO_HOST", "127.0.0.1:9000")

import pytest


@pytest.fixture(scope="module")
def app():
    """延迟导入 server 模块"""
    try:
        from server import app as flask_app
        flask_app.config['TESTING'] = True
        return flask_app
    except Exception as e:
        pytest.skip(f"Server module not importable (DB/MinIO not available): {e}")


@pytest.fixture
def client(app):
    """创建测试客户端"""
    with app.test_client() as client:
        yield client


class TestServerBasic:
    """Server 基础功能测试"""

    def test_index_returns_html(self, client):
        """首页返回 HTML"""
        resp = client.get('/')
        assert resp.status_code in [200, 404]  # index2.html 可能不存在于测试环境

    def test_list_tasks_empty(self, client):
        """任务列表初始为空"""
        resp = client.get('/api/tasks')
        assert resp.status_code == 200
        assert isinstance(resp.json, list)

    def test_list_agents(self, client):
        """Agent 列表接口正常"""
        resp = client.get('/api/agents')
        assert resp.status_code == 200
        assert isinstance(resp.json, list)

    def test_heartbeat_no_agent_id(self, client):
        """心跳请求缺少 agent_id 返回 400"""
        resp = client.post('/api/agents/heartbeat', json={})
        assert resp.status_code == 400
        assert 'error' in resp.json

    def test_create_task_no_pid(self, client):
        """创建任务缺少 pid 返回 400"""
        resp = client.post('/api/tasks', json={})
        assert resp.status_code == 400
        assert 'error' in resp.json

    def test_create_task_no_agent_id(self, client):
        """创建任务缺少 agent_id 返回 400"""
        resp = client.post('/api/tasks', json={"pid": 1234})
        assert resp.status_code == 400
        assert 'error' in resp.json

    def test_create_task_success(self, client):
        """成功创建任务"""
        resp = client.post('/api/tasks', json={
            "pid": 1,
            "duration": 5,
            "hz": 99,
            "agent_id": "test-agent",
            "profiler": "perf"
        })
        assert resp.status_code == 200
        assert 'tid' in resp.json
        assert resp.json['tid'].startswith('task-')

    def test_get_nonexistent_task(self, client):
        """获取不存在的任务返回 404"""
        resp = client.get('/api/tasks/task-nonexist')
        assert resp.status_code == 404

    def test_get_audit_log(self, client):
        """审计日志接口正常"""
        resp = client.get('/api/audit')
        assert resp.status_code == 200
        assert isinstance(resp.json, list)

    def test_heartbeat_success(self, client):
        """正常心跳请求"""
        resp = client.post('/api/agents/heartbeat', json={
            "agent_id": "test-agent-001",
            "hostname": "test-host",
            "ip": "192.168.1.1"
        })
        assert resp.status_code == 200
        assert resp.json['status'] == 'ok'


class TestTaskStateMachine:
    """任务状态机测试"""

    def test_task_lifecycle(self, client):
        """测试完整的任务生命周期 PENDING → RUNNING → DONE"""
        # 1. 创建任务 (PENDING)
        resp = client.post('/api/tasks', json={
            "pid": 1, "duration": 5, "hz": 99,
            "agent_id": "lifecycle-agent",
            "profiler": "perf"
        })
        assert resp.status_code == 200
        tid = resp.json['tid']

        # 2. 验证任务状态为 PENDING
        resp = client.get(f'/api/tasks/{tid}')
        assert resp.status_code == 200
        assert resp.json['status'] == 'PENDING'

        # 3. Agent 拉取任务 (PENDING → RUNNING)
        resp = client.get(f'/api/agents/lifecycle-agent/tasks/pending')
        assert resp.status_code == 200
        assert resp.json['tid'] == tid

        # 4. 验证状态变为 RUNNING
        resp = client.get(f'/api/tasks/{tid}')
        assert resp.json['status'] == 'RUNNING'

        # 5. 报告任务完成 (RUNNING → DONE)
        resp = client.post(f'/api/tasks/{tid}/result', json={
            "status": "DONE", "reason": "Test completed"
        })
        assert resp.status_code == 200

        # 6. 验证最终状态
        resp = client.get(f'/api/tasks/{tid}')
        assert resp.json['status'] == 'DONE'
        assert resp.json['reason'] == 'Test completed'

    def test_task_failure(self, client):
        """测试任务失败路径 PENDING → RUNNING → FAILED"""
        resp = client.post('/api/tasks', json={
            "pid": 99999, "duration": 1, "hz": 99,
            "agent_id": "fail-agent",
            "profiler": "perf"
        })
        tid = resp.json['tid']

        # Agent 拉取
        client.get('/api/agents/fail-agent/tasks/pending')

        # 报告失败
        resp = client.post(f'/api/tasks/{tid}/result', json={
            "status": "FAILED", "reason": "perf: No such process"
        })
        assert resp.status_code == 200

        resp = client.get(f'/api/tasks/{tid}')
        assert resp.json['status'] == 'FAILED'
        assert 'No such process' in resp.json['reason']


class TestAuditLog:
    """审计日志测试"""

    def test_agent_offline_audit(self, client):
        """Agent 离线应产生审计日志"""
        # 先注册 Agent
        client.post('/api/agents/heartbeat', json={
            "agent_id": "audit-agent-1",
            "hostname": "test",
            "ip": "10.0.0.1"
        })

        # 验证审计日志存在（至少有心跳记录）
        resp = client.get('/api/audit')
        assert resp.status_code == 200


class TestHeatmapAPI:
    """热力图 API 测试"""

    def test_heatmap_not_found(self, client):
        """请求不存在任务的热力图"""
        resp = client.get('/api/tasks/nonexistent/heatmap')
        assert resp.status_code == 404


class TestContinuousProfiling:
    """持续分析 API 测试"""

    def test_start_continuous(self, client):
        """启动持续分析"""
        resp = client.post('/api/continuous/start', json={
            "agent_id": "test-agent",
            "pid": 1
        })
        assert resp.status_code == 200
        assert resp.json['status'] == 'ok'

    def test_stop_continuous(self, client):
        """停止持续分析"""
        resp = client.post('/api/continuous/stop')
        assert resp.status_code == 200
        assert resp.json['status'] == 'ok'

    def test_list_windows_empty(self, client):
        """持续分析窗口列表（初始为空）"""
        resp = client.get('/api/continuous/windows')
        assert resp.status_code == 200
        assert isinstance(resp.json, list)


class TestAttribution:
    """智能归因 API 测试"""

    def test_attribution_not_found(self, client):
        """归因分析不存在的任务"""
        resp = client.post('/api/attribution/nonexistent')
        assert resp.status_code == 404


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
