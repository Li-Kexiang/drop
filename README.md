# Drop 性能分析系统

Drop 是一个面向 Linux 服务器与容器场景的**一站式性能采集与可视化分析平台**。用户通过 Web UI 下发采集任务，Agent 支持 **perf / eBPF / py-spy** 三种采集器，分析后生成火焰图、热力图和 **LLM 智能归因报告**。

## 硬件 / 内核 / 权限要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 22.04+ / WSL2 / Linux 发行版 |
| 内核版本 | Linux 5.4+（perf），推荐 5.15+（eBPF 支持更好） |
| Python | 3.10+ |
| 依赖工具 | perf（linux-tools）、bpftrace（eBPF）、py-spy（Python） |

## 一键运行

### 开发模式（推荐，支持全部采集器）

```bash
git clone https://github.com/Li-Kexiang/drop.git
cd drop
make dev
# 浏览器访问：http://localhost:5000
```

`make dev` 自动完成：创建 venv → 安装依赖 → 设置 perf 权限 → 启动全部服务 + Cloudflare 公网隧道。

> **WSL2 用户**：首次使用前在 Windows PowerShell 执行一次 `wsl --shutdown`，然后重新打开 WSL 即可通过 `localhost:5000` 访问。

### Docker 模式（部署演示）

```bash
git clone https://github.com/Li-Kexiang/drop.git
cd drop
make demo-docker
# Web UI:  http://localhost:5000
# MinIO:   http://localhost:9001 (drop/drop1234)
```

> Docker 模式下 Agent 运行在容器内，perf/eBPF/py-spy 采集受容器权限限制，主要用于部署架构演示。

## 三种采集器

| 采集器 | 适用场景 | 状态 |
|--------|----------|------|
| **perf (CPU)** | CPU 热点分析，采样内核+用户态调用栈 | ✅ |
| **eBPF (IO事件)** | IO 系统调用追踪（read/write 等） | ✅ |
| **py-spy (Python)** | Python 进程用户态栈分析 | ✅ |

## 使用说明

### 快速开始（单次采集）

1. 启动一个测试用的 Python 进程：
   ```bash
   python3 -c "import hashlib; [hashlib.sha256(b'x'*100000).hexdigest() for _ in iter(int,1)]" &
   echo "PID: $!"
   ```

2. 在 Web UI (`http://localhost:5000`) 填入 PID，选采集器，点「开始采集」

3. 等待状态变为 **DONE**，查看火焰图、热力图和 LLM 智能归因

### 持续分析（定时自动采集）

切换到 **📊 持续分析** 标签页，可配置：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| PID | 目标进程 | 1 |
| 间隔(s) | 两次采集之间等待时长 | 30 |
| 时长(s) | 每次采集持续时长 | 5 |

点击「启动持续分析」，Agent 按设定节奏自动反复采集，每个时间窗口独立生成火焰图和热力图。
Agent 每次循环从 Server 动态读取配置，支持运行时修改参数（无需重启）。

### perf 权限

若 perf 采集失败，降低安全限制：
```bash
sudo sysctl -w kernel.perf_event_paranoid=0
sudo sysctl -w kernel.yama.ptrace_scope=0
```

### py-spy 注意事项

- 目标必须是 **Python 进程**（`ps aux | grep python` 查找）
- 进程需要有**持续计算负载**才会产生足够采样数据
- 空闲进程可能提示 "No stack counts found"，换活跃进程即可

### 智能归因

任务完成后，点击「🤖 归因」按钮：
- 系统自动拉取火焰图数据和采集元信息
- 结合 LLM（可选）或内置规则引擎，产出可验证的归因结论
- 包含热点识别、根因分析、优化建议、置信度和验证方法

## Make 命令

| 命令 | 说明 |
|------|------|
| `make dev` | 开发模式一键启动（SQLite + 本地存储） |
| `make demo` | Docker 模式启动（PostgreSQL + MinIO） |
| `make help` | 查看所有命令 |
| `make clean` | 清理环境 |
| `make test` | 运行单元测试 |

## 目录结构

```
drop/
├── server.py              # API 服务（Flask + PostgreSQL/SQLite）
├── agent.py               # 采集 Agent（perf / eBPF / py-spy）
├── analyzer.py            # 分析器（火焰图 / 热力图 / LLM 归因）
├── dev_launcher.py        # 开发模式启动器
├── start_all.sh           # 一键启动脚本（含公网隧道）
├── start_dev.sh           # 开发模式启动脚本
├── index2.html            # Web UI（单页应用）
├── static/                # 本地 JS 库（axios, echarts）
├── tests/                 # 单元测试 & 端到端测试
├── docs/                  # 设计文档
├── Makefile               # Make 命令
├── docker-compose.yml     # Docker 编排
├── Dockerfile             # Docker 镜像
└── requirements.txt       # Python 依赖
```

## 采集器对比

| 采集类型 | 工具 | 适用场景 | 可视化 |
|----------|------|----------|--------|
| perf | Linux perf | CPU 采样，所有环境 | 火焰图 + 热力图 |
| eBPF | bpftrace | IO 事件，原生 Linux | 火焰图 + 热力图 |
| py-spy | py-spy | Python 应用，用户态栈 | 火焰图 + 热力图 |

## 智能归因

任务完成后，点击「🤖 归因」按钮，系统支持两种模式：
1. **LLM 模式**：设置环境变量 `LLM_ENDPOINT`、`LLM_API_KEY`、`LLM_MODEL`，调用 OpenAI 兼容 API
2. **规则模式**（默认）：基于函数名模式匹配 + 采样数据统计，离线可用

产出包含热点识别、根因分析、优化建议、置信度和验证方法。

## 演示视频

视频链接：https://share.weiyun.com/Z33242uo
后续调试过程中新版本的drop功能演示视频链接：
https://share.weiyun.com/ZK6iRYFi

## 设计文档

详细架构、状态机迁移图、关键决策、性能自证等见 [docs/design.md](docs/design.md)。
