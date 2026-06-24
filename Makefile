.PHONY: demo demo-docker up down clean test e2e help

# 默认目标
help:
	@echo "Drop - 一站式性能分析平台"
	@echo ""
	@echo "用法:"
	@echo "  make demo         本地开发模式启动（Python 虚拟环境 + 独立 Docker 容器）"
	@echo "  make demo-docker  一键 Docker Compose 启动"
	@echo "  make up           Docker Compose 启动"
	@echo "  make down         Docker Compose 停止"
	@echo "  make test         运行单元测试"
	@echo "  make e2e          运行端到端集成测试"
	@echo "  make clean        清理环境"

# Docker Compose 一键启动 (推荐)
demo-docker: up
	@echo ""
	@echo "===== Drop 启动完成 ====="
	@echo "Web UI:   http://localhost:5000"
	@echo "MinIO控制台: http://localhost:9001 (drop/drop1234)"
	@echo ""

up:
	docker compose up -d --build
	@echo "等待服务就绪..."
	@sleep 8
	@echo "===== 部署完成 ====="

down:
	docker compose down -v

# 本地开发模式
demo:
	@echo "启动 Drop 系统（本地开发模式）..."
	@echo "创建虚拟环境..."
	python3 -m venv venv || true
	venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
	@echo "启动 PostgreSQL 和 MinIO..."
	-docker run -d --name postgres-single -p 5433:5432 -e POSTGRES_DB=drop -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgres postgres:14
	-docker run -d --name minio-single -p 9000:9000 -p 9001:9001 -e MINIO_ROOT_USER=drop -e MINIO_ROOT_PASSWORD=drop1234 minio/minio server /data --console-address ":9001"
	sleep 5
	@echo "创建 drop 桶并设置为公开..."
	venv/bin/python setup_minio.py
	@echo "启动微服务..."
	venv/bin/python server.py &
	venv/bin/python agent.py &
	venv/bin/python analyzer.py &
	sleep 3
	@echo ""
	@echo "===== 部署完成 ====="
	@echo "访问 http://localhost:5000"
	@echo "使用说明："
	@echo "1. 在 Web 界面填写一个活跃 PID（可通过 'echo $$' 获取）"
	@echo "2. 设置时长（如 5 秒），选择采集器类型，点击采集"
	@echo "3. 等待任务完成，点击火焰图/热力图查看"
	@echo ""

# 测试
test:
	venv/bin/python -m pytest tests/ -v --cov=. --cov-report=term-missing || python -m pytest tests/ -v

e2e:
	venv/bin/python tests/test_e2e.py

# 清理
clean:
	pkill -f "python.*server.py" 2>/dev/null || true
	pkill -f "python.*agent.py" 2>/dev/null || true
	pkill -f "python.*analyzer.py" 2>/dev/null || true
	-docker stop postgres-single minio-single 2>/dev/null || true
	-docker rm postgres-single minio-single 2>/dev/null || true
	rm -rf venv/ __pycache__/ .pytest_cache/ /tmp/*.perf.data /tmp/*.svg /tmp/*.folded 2>/dev/null || true
	@echo "清理完成"
