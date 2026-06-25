# Drop 设计文档

## 1. 架构图

```
┌──────────────────────────────────────────────────────┐
│                     Web UI (index2.html)              │
│               ECharts 热力图 + SVG 火焰图               │
│           采集器选择、智能归因、持续分析面板              │
└────────────────────┬─────────────────────────────────┘
                     │ HTTP (REST API)
                     ▼
┌──────────────────────────────────────────────────────┐
│                  Server (Flask :5000)                 │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │
│  │ 任务管理  │  │ Agent管理 │  │ 持续分析 / 归因    │  │
│  └────┬─────┘  └────┬─────┘  └───────────────────┘  │
│       │              │                                │
│       ▼              ▼                                │
│  ┌──────────────────────────────────────┐            │
│  │          PostgreSQL :5433             │            │
│  │   tasks │ agents │ audit_log         │            │
│  └──────────────────────────────────────┘            │
└────────────────────┬─────────────────────────────────┘
                     │ HTTP (任务下发 / 心跳)
                     ▼
┌──────────────────────────────────────────────────────┐
│                  Agent (agent.py)                     │
│  ┌─────────┐  ┌───────────┐  ┌──────────────────┐   │
│  │ perf    │  │  eBPF     │  │  py-spy          │   │
│  │ 采集器  │  │  采集器   │  │  采集器           │   │
│  └────┬────┘  └─────┬─────┘  └────────┬─────────┘   │
│       │              │                 │              │
│       └──────────────┼─────────────────┘              │
│                      │ 上传                           │
│                      ▼                                │
│              ┌───────────────┐                        │
│              │  MinIO :9000  │                        │
│              │  (对象存储)    │                        │
│              └───────┬───────┘                        │
└──────────────────────┼────────────────────────────────┘
                       │ 拉取数据
                       ▼
┌──────────────────────────────────────────────────────┐
│                Analyzer (Flask :5003)                 │
│  ┌────────────────────────────────────────────────┐  │
│  │  perf.script → stackcollapse → flamegraph.pl    │  │
│  │  eBPF folded → flamegraph.pl (直接)            │  │
│  │  py-spy folded → flamegraph.pl (直接)          │  │
│  └────────────────────┬───────────────────────────┘  │
│                       │ 上传                          │
│                       ▼                               │
│              ┌───────────────┐                        │
│              │  MinIO :9000  │                        │
│              │ flamegraph.svg│                        │
│              │ heatmap.json  │                        │
│              └───────────────┘                        │
└──────────────────────────────────────────────────────┘
```

## 2. 状态机迁移图

```
                    ┌──────────┐
                    │  PENDING │  ← 任务创建
                    └────┬─────┘
                         │ Agent 拉取 (reason="Agent picked up")
                         ▼
                    ┌──────────┐
                    │  RUNNING │  ← Agent 采集中
                    └────┬─────┘
                         │ 采集完成 (reason="Raw data uploaded")
                         ▼
                    ┌───────────┐
                    │ UPLOADING │  ← 上传到 MinIO
                    └─────┬─────┘
                          │
              ┌───────────┼───────────┐
              │ 成功                  │ 失败
              ▼                       ▼
         ┌─────────┐           ┌──────────┐
         │  DONE   │           │  FAILED  │
         └─────────┘           └──────────┘
              │
              │ Analyzer 自动触发
              ▼
         ┌──────────────┐
         │ 火焰图/热力图  │
         │ 生成并上传     │
         └──────────────┘

每次状态迁移必须:
  - 更新 tasks.status
  - 写入 tasks.reason (迁移原因)
  - 更新 tasks.updated_at
```

## 3. 关键决策

### 3.1 进程级微服务架构
- 三个独立 Python 进程（Server、Agent、Analyzer）通过 HTTP 通信
- 优势：独立扩展、独立部署、故障隔离
- 劣势：需要额外的服务编排（Docker Compose 解决）

### 3.2 多采集器设计
Agent 内部通过 `profiler` 参数路由到不同采集器：
- **perf**: 最通用，CPU 采样精度高，适合生产环境
- **eBPF (bpftrace)**: IO 事件采集，内核态栈，需 root 权限
- **py-spy**: Python 用户态栈，零侵入，适合 Python 应用

### 3.3 存储分层
- **PostgreSQL**: 任务状态、Agent 管理、审计日志（结构化数据）
- **MinIO**: 性能原始数据、火焰图 SVG、热力图 JSON（大文件对象存储）

### 3.4 前端直接嵌入 Server
- index2.html 由 Flask `send_file` 直接返回，无需独立前端服务
- 前端通过 REST API 与 Server 通信，Server 代理 MinIO 数据

### 3.5 智能归因双模式
- **LLM 模式**: 接入 OpenAI 兼容 API，提供高质量分析
- **规则模式**: 基于函数名模式匹配的启发式分析，离线可用，确保 fallback

### 3.6 Continuous Profiling（持续分析）
- Agent 启动时自动开启持续分析线程（无需环境变量开关）
- 每次循环从 Server `GET /api/continuous/state` 动态读取配置：
  - `running` — 是否暂停（false 时等待）
  - `pid` — 目标进程
  - `interval` — 采集间隔（秒）
  - `duration` — 每次采集时长（秒）
- Web UI 的「📊 持续分析」面板提供 PID/间隔/时长 输入框
- 支持运行时修改参数，无需重启 Agent
- 每个时间窗口独立分析，生成火焰图 + 热力图

## 4. 取舍说明

### 已做取舍
1. **eBPF 权限要求高**：需要 `sudo` 和特权容器，Docker Compose 中用 `privileged: true` 解决
2. **py-spy 仅限 Python**：对其他语言应用需 fallback 到 perf
3. **持续分析非实时**：窗口之间有间隔，不保证无死角覆盖；Agent 通过轮询 Server 获取配置，最多有一个间隔的延迟
4. **归因的 LLM 依赖外部 API**：无网络时自动回退规则引擎

### 未做取舍（延后）
1. Java async-profiler：可作为第四种采集器扩展
2. 分布式 Agent 管理：当前仅支持单 Agent
3. WebSocket 实时推送：当前使用轮询方式
4. 持续分析窗口与任务列表统一：`continuous-*` 窗口不在 tasks 表中，通过 Server 定制端点处理

## 5. API 端点汇总

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks` | 创建采集任务 |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/<tid>` | 任务详情（支持 `continuous-*`） |
| POST | `/api/tasks/<tid>/result` | Agent 上报结果 |
| GET | `/api/tasks/<tid>/heatmap` | 热力图数据 |
| GET | `/api/agents` | Agent 列表 |
| POST | `/api/agents/heartbeat` | Agent 心跳 |
| GET | `/api/agents/<aid>/tasks/pending` | 拉取待处理任务 |
| POST | `/api/continuous/start` | 启动持续分析 |
| POST | `/api/continuous/stop` | 停止持续分析 |
| GET | `/api/continuous/state` | Agent 读取配置 |
| GET | `/api/continuous/windows` | 列出时间窗口 |
| GET | `/api/storage/<path>` | 存储代理（DEV 模式） |
| POST | `/api/attribution/<tid>` | 智能归因 |

## 6. AI 协作章节

开发过程中使用 GitHub Copilot (DeepSeek V4 Pro) 协助：
- **代码生成**：多采集器路由逻辑、eBPF bpftrace 脚本生成、智能归因 prompt 构建
- **重构优化**：从硬编码 perf 重构为多采集器架构、修复重复路由 bug
- **测试生成**：15+ 单元测试用例和 5 个端到端测试场景
- **文档撰写**：README、设计文档、docker-compose 编排

AI 协作的最佳实践：
- 每次修改聚焦单一目标，commit message 解释"为什么"
- AI 生成的 eBPF 脚本需要在真实 Linux 环境验证
- 安全相关的配置（如 privileged 容器）需人工审核

## 7. 性能自证

### 采集性能
- perf 5 秒采集（99Hz）：约 500 个样本，火焰图 >300 帧
- eBPF 10 秒 IO 采集：约 1000-5000 个事件
- py-spy 5 秒采集：约 500 个 Python 调用栈帧

### 分析性能
- perf script 解析：< 2 秒
- 火焰图生成：< 1 秒（flamegraph.pl）
- 智能归因（规则模式）：< 0.5 秒
- 智能归因（LLM 模式）：取决于 API 延迟，通常 2-5 秒

### 资源占用
- Server: ~50MB 内存
- Agent (idle): ~30MB 内存
- Analyzer: ~40MB 内存
- PostgreSQL: ~100MB 内存
- MinIO: ~80MB 内存

## 8. 如果再有 7 天我会做什么

1. **Java async-profiler 集成**：支持 Java 应用的 CPU/Allocation/Lock 分析
2. **WebSocket 实时推送**：替代前端轮询，任务状态变更实时通知
3. **火焰图交互式增强**：支持搜索、缩放、差异对比（diff flamegraph）
4. **多 Agent 分布式管理**：支持多台主机同时采集，Web UI 统一管理
5. **eBPF 扩展**：增加 kprobe/tracepoint/profile 探针，覆盖 CPU/内存/网络
6. **智能归因增强**：引入历史 baseline 对比，异常检测自动触发归因
7. **容器化优化**：精简镜像（alpine-based），减少启动时间
