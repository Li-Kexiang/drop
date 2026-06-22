# Drop 性能分析系统

Drop 是一个面向 Linux 服务器与容器场景的按需性能采集与可视化分析平台。用户通过 Web UI 下发 perf 采集任务，Agent 采集目标进程的 CPU 调用栈，分析后生成火焰图、热力图和优化建议。

## 硬件 / 内核 / 权限要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 22.04 LTS（或其它 Linux 发行版） |
| 内核版本 | Linux 5.4+（支持 perf） |
| 权限 | 需设置 `sudo sysctl -w kernel.perf_event_paranoid=0` |
| Docker | Docker 20.10+，Docker Compose 2.0+ |

## 一键运行

```bash
git clone https://github.com/Li-Kexiang/drop.git
cd drop
make demo
浏览器访问：http://localhost:5000
使用说明
在 Web 界面填写 PID（可通过 echo $$ 获取当前 Shell 的 PID）

设置时长（建议 5 秒），点击采集

等待任务完成，点击火焰图查看
目录结构
drop/
├── server.py       # API 服务
├── agent.py        # 采集 Agent
├── analyzer.py     # 分析生成火焰图
├── index.html      # Web 界面
├── Dockerfile
├── docker-compose.yml
├── Makefile
└── README.md

## MinIO 控制台

性能数据存储在 MinIO 中，可通过浏览器访问：
- 地址：http://localhost:9001
- 账号：drop
- 密码：drop1234
## 演示视频
https://share.weiyun.com/9KDZCGmY

## 补充说明：eBPF 采集

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
详细说明见 scripts/ebpf_demo.sh。

## 设计文档

详细架构、状态机迁移图、关键决策、性能自证等见 [docs/design.md](docs/design.md)。

## 演示视频

[点击观看演示视频](https://share.weiyun.com/9KDZCGMy)

## 补充说明：eBPF 采集

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
详细说明见 scripts/ebpf_demo.sh。

## 补充说明：eBPF 采集

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
详细说明见 scripts/ebpf_demo.sh。

## 设计文档

详细架构、状态机迁移图、关键决策、性能自证等见 [docs/design.md](docs/design.md)。

## 演示视频

[点击观看演示视频](https://share.weiyun.com/9KDZCGMy)

## 补充说明：eBPF 采集

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
详细说明见 scripts/ebpf_demo.sh。
