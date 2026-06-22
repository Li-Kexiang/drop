.PHONY: demo

demo:
	@echo "启动 Drop 系统..."
	@echo "创建虚拟环境..."
	python3 -m venv venv || true
	venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ flask flask-cors psycopg2-binary minio requests python-dotenv
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
	@echo "2. 设置时长（如 5 秒），选择 'perf'，点击采集"
	@echo "3. 等待任务完成，点击 '火焰图' 查看"
	@echo ""
