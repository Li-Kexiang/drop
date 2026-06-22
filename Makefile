.PHONY: demo
demo:
	@echo "启动 Drop 系统..."
	docker compose up -d
	sleep 5
	@echo "访问 http://localhost:5000"
	@echo "使用说明："
	@echo "1. 在 Web 界面填写一个活跃 PID（可通过 'echo $$' 获取）"
	@echo "2. 设置时长（如 5 秒），选择 'perf'，点击采集"
	@echo "3. 等待任务完成，点击 '火焰图' 查看"
