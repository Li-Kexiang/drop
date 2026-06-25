.PHONY: demo dev demo-docker up down clean test e2e help

# 默认目标
help:
	@echo "Drop - 一站式性能分析平台"
	@echo ""
	@echo "用法:"
	@echo "  make dev          开发模式一键启动（SQLite + 本地存储）"
	@echo "  make demo         Docker 模式启动（PostgreSQL + MinIO）"
	@echo "  make demo-docker  一键 Docker Compose 启动"
	@echo "  make up           Docker Compose 启动"
	@echo "  make down         Docker Compose 停止"
	@echo "  make test         运行单元测试"
	@echo "  make e2e          运行端到端集成测试"
	@echo "  make clean        清理环境"

# ========== 开发模式一键启动（推荐）==========
dev:
	@echo "🔥 Drop 开发模式一键启动..."
	@echo ""
	@# 检查并设置 perf 权限
	@if [ "$$(cat /proc/sys/kernel/perf_event_paranoid 2>/dev/null)" != "0" ]; then \
		echo "🔧 降低 perf 安全限制..."; \
		sudo sysctl -w kernel.perf_event_paranoid=0 2>/dev/null || echo "⚠️  请手动执行: sudo sysctl -w kernel.perf_event_paranoid=0"; \
		sudo sysctl -w kernel.yama.ptrace_scope=0 2>/dev/null || echo "⚠️  请手动执行: sudo sysctl -w kernel.yama.ptrace_scope=0"; \
	fi
	@# 创建 venv + 安装依赖（去掉 -q 避免静默失败）
	@NEED_INSTALL=0; \
	if [ ! -d "venv" ]; then \
		echo "📦 创建虚拟环境..."; \
		python3 -m venv venv; \
		NEED_INSTALL=1; \
	elif ! venv/bin/python -c "import flask, requests" 2>/dev/null; then \
		echo "📦 检测到依赖缺失，重新安装..."; \
		NEED_INSTALL=1; \
	fi; \
	if [ "$$NEED_INSTALL" = "1" ]; then \
		venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt || { \
			echo "❌ pip 安装失败！请手动执行: venv/bin/pip install -r requirements.txt"; \
			exit 1; \
		}; \
	fi
	@# 下载 cloudflared
	@if [ ! -f "/tmp/cloudflared" ]; then \
		curl -sL -o /tmp/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64; \
		chmod +x /tmp/cloudflared; \
	fi
	@echo ""
	@echo "🚀 启动所有服务..."
	@bash start_all.sh

# Docker Compose 一键启动
demo: up
	@echo ""
	@echo "===== Drop 启动完成 ====="
	@echo "Web UI:   http://localhost:5000"
	@echo "MinIO控制台: http://localhost:9001 (drop/drop1234)"
	@echo ""

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
