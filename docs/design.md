# Drop 设计文档

## 1. 架构图

+------------------+     HTTP      +------------------+
|   Web UI         | -------------> |   Server (5000)  |
|   (index.html)   | <------------- |   (server.py)    |
+------------------+                +--------+---------+
                                           |
                                           | (任务下发)
                                           v
                                    +------------------+
                                    |   Agent          |
                                    |   (agent.py)     |
                                    +--------+---------+
                                           |
                                           | (perf/eBPF 采集 + 上传 MinIO)
                                           v
                                    +------------------+
                                    |   MinIO (9000)   |
                                    |   (存储数据)     |
                                    +------------------+
                                           |
                                           | (Analyzer 拉取)
                                           v
                                    +------------------+
                                    |   Analyzer(5003) |
                                    |   (analyzer.py)  |
                                    +------------------+
                                           |
                                           | (生成火焰图/热力图)
                                           v
                                    +------------------+
                                    |   PostgreSQL     |
                                    |   (5433)         |
                                    +------------------+

## 2. 状态机迁移图

PENDING → RUNNING → UPLOADING → DONE
        ↘ FAILED

- **PENDING**：任务已创建，等待 Agent 拉取
- **RUNNING**：Agent 已拉取，正在采集
- **UPLOADING**：采集完成，上传到 MinIO
- **DONE**：分析完成，可查看火焰图
- **FAILED**：采集或分析失败（带 reason）

## 3. 关键决策

- 选择进程级微服务架构，三个独立 Python 进程（Server、Agent、Analyzer）通过 HTTP 通信，便于独立扩展和维护，同时避免容器编排的复杂性。
- PostgreSQL 存任务状态和审计日志，MinIO 存性能数据，职责清晰
- 前端直接嵌入 server.py，简化部署，避免单独前端服务
- eBPF 采集器已集成到 Agent 中（execute_ebpf_task 函数）
  使用 bpftrace 采集 tracepoint:syscalls:sys_enter_read 事件
  在 WSL2 环境下受限，原生 Linux 可正常运行
  提供演示脚本 scripts/ebpf_demo.sh
- 在文档中增加采集类型说明：

采集类型	工具	           适用场景
perf	Linux perf	CPU 采样，所有环境
eBPF	bpftrace	          IO 事件，原生 Linux

## 4. 取舍说明

- eBPF 仅支持原生 Linux：WSL2 下 eBPF 受限，演示时在云服务器运行
- 未做持续 profiling：可由定时任务 + 历史任务列表替代

## 5. AI 协作

开发过程中使用Deepseek协助编写代码、调试错误、生成文档，大幅提高开发效率。

## 6. 性能自证

- 在 Ubuntu 22.04 上，perf 采集 5 秒可获取约 500 个样本，火焰图清晰显示热点函数
- 热力图基于 Top 30 函数生成，渲染流畅

## 7. 如果再有 7 天

1. 完善 eBPF 采集器，支持更多事件类型
   扩展 eBPF 采集器：支持更多探针类型：kprobe、tracepoint、profile，覆盖 CPU、内存、IO、网络等更多场景；支持动态配置采集事件，用户可在 Web 界面选择要监控的内核事件；提供 eBPF 采集结果的独立可视化面板（区别于 perf 火焰图）
2. 加入持续 profiling，后台定时采集，时间轴回溯
3. 容器化优化，减少镜像大小和启动时间
4. 增加智能归因（LLM 分析火焰图给出优化建议）
5. 增加更多语言支持（Java async-profiler、Python py-spy）
