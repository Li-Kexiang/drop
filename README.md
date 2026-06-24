# Drop 性能分析系统

Drop 是一个面向 Linux 服务器与容器场景的**一站式性能采集与可视化分析平台**。用户通过 Web UI 下发采集任务，Agent 支持 **perf / eBPF / py-spy** 三种采集器，分析后生成火焰图、热力图和 **LLM 智能归因报告**。

## 硬件 / 内核 / 权限要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 22.04 LTS（或其它 Linux 发行版） |
| 内核版本 | Linux 5.4+（支持 perf），推荐 5.15+（eBPF 支持更好） |
| 权限 | `sudo sysctl -w kernel.perf_event_paranoid=0` |
|       | eBPF 采集需 `sudo` 权限运行 bpftrace |
| Docker | Docker 20.10+，Docker Compose 2.0+ |
| Python | 3.10+ |

## 一键运行

### 方式一：Docker Compose（推荐）

```bash
git clone https://github.com/Li-Kexiang/drop.git
cd drop
make demo-docker
# 浏览器访问：http://localhost:5000
```

### 方式二：本地开发模式

```bash
git clone https://github.com/Li-Kexiang/drop.git
cd drop
make demo
# 浏览器访问：http://localhost:5000
```

## 使用说明

### 基础采集

1. 在 Web 界面填写目标 **PID**（可通过 `echo $$` 获取当前 Shell 的 PID）
2. 设置**采样时长**（建议 5-10 秒）
3. 选择**采集器**：
   - **perf (CPU)** — Linux perf 采样 CPU 调用栈，适合 CPU 热点分析
   - **eBPF (IO事件)** — bpftrace 采集 IO 系统调用（read/write），需原生 Linux
   - **py-spy (Python)** — py-spy 采集 Python 进程用户态栈，适合 Python 应用
4. 点击"开始采集"，等待任务状态变为 DONE
5. 点击"火焰图"/"热力图"查看结果

### 智能归因

任务完成后，点击"归因"按钮：
- 系统自动拉取火焰图数据和采集元信息
- 结合 LLM（可选）或内置规则引擎，产出可验证的归因结论
- 包含热点识别、根因分析、优化建议、置信度和验证方法

### eBPF 现场演示

```bash
# 终端1: 制造 IO 负载
dd if=/dev/zero of=/tmp/testfile bs=1M count=1000

# 终端2: 找到 dd 的 PID
ps aux | grep dd

# Web UI: 选择 eBPF 采集器，填入 dd 的 PID，采集 10s
# 观察火焰图中 read/write 相关调用的分布变化
```

### Continuous Profiling（持续分析）

在 Web UI 的"持续分析"标签页：
- 点击"启动持续分析"，设置目标 PID
- 每 60 秒自动采集 5 秒窗口，自动切割存储
- 可在时间轴上点击任意窗口回溯火焰图

## 目录结构

```
drop/
├── server.py              # API 服务（Flask + PostgreSQL）
├── agent.py               # 采集 Agent（perf / eBPF / py-spy）
├── analyzer.py            # 分析引擎（火焰图 + 热力图）
├── index2.html            # Web UI（ECharts + SVG 火焰图）
├── Dockerfile             # Docker 镜像
├── docker-compose.yml     # Docker Compose 编排
├── Makefile               # 构建和测试命令
├── requirements.txt       # Python 依赖
├── setup_minio.py         # MinIO 初始化脚本
├── start.sh               # 旧版启动脚本
├── tests/
│   ├── test_server.py     # 单元测试（≥ 15 用例）
│   └── test_e2e.py        # 端到端集成测试（5 场景）
└── docs/
    └── design.md           # 设计文档
```

## 运行测试

```bash
# 单元测试
make test

# 集成测试（需要 Server 已启动）
make e2e
```

## MinIO 控制台

性能数据存储在 MinIO 中，可通过浏览器访问：
- 地址：http://localhost:9001
- 账号：drop
- 密码：drop1234

## 采集器对比

| 采集类型 | 工具 | 适用场景 | 可视化 |
|----------|------|----------|--------|
| perf | Linux perf | CPU 采样，所有环境 | 火焰图 + 热力图 |
| eBPF | bpftrace | IO 事件，原生 Linux | 火焰图 + 热力图 |
| py-spy | py-spy | Python 应用，用户态栈 | 火焰图 + 热力图 |

## 智能归因

归因系统支持两种模式：
1. **LLM 模式**：设置环境变量 `LLM_ENDPOINT`、`LLM_API_KEY`、`LLM_MODEL`，调用 OpenAI 兼容 API
2. **规则模式**（默认）：基于函数名模式匹配 + 采样数据统计，离线可用

## 演示视频

视频链接：https://share.weiyun.com/Z33242uo

本系统已集成 eBPF 采集器，支持通过 `bpftrace` 采集 IO 事件并生成火焰图。

> **为什么视频中没有演示？**  
> 演示环境为 WSL2，eBPF 支持受限。eBPF 采集器已在代码中完整实现，可直接在原生 Linux（Ubuntu 22.04）上运行。

### 在原生 Linux 上运行 eBPF

1. 安装 `bpftrace`：
   ```bash
   sudo apt install bpftrace
运行演示脚本：
./scripts/ebpf_demo.sh
在 Web 界面选择 eBPF (IO事件)，填入 dd 进程的 PID，点击采集，火焰图会显示 vfs_read、__do_sys_read 等内核函数。

## 设计文档

详细架构、状态机迁移图、关键决策、性能自证等见 [docs/design.md](docs/design.md)。


详细说明见 scripts/ebpf_demo.sh。
