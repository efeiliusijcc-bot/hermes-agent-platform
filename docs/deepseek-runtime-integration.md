# DeepSeek Harness Runtime 接入说明

## 1. 结论与版本边界

平台按 DeepSeek 官方仓库 `deepseek-ai/deepseek-harness` 的公开契约接入 Coding Runtime。2026-08-17 核对的官方信息如下：

- 官方仓库仍标记为 Developer Preview，并明确提示后续可能发生破坏兼容的变更；
- 官方 SDK Runtime 协议是 stdio 上逐行 JSON-RPC 2.0，不是 HTTP；
- 当前协议请求只有 `initialize`、`session/prompt`、`shutdown`，通知包括 `session.event` 与 `session.status`；
- 协议没有单 Session cancel/close，停止执行必须终止对应 Runtime 进程；
- 平台固定使用官方 npm `0.1.0-rc.6` 的 SDK JSON-RPC、Agent、DeepSeek Adapter、JSONL Session、本地 bash 和本地 filesystem 包；
- 所有 npm 直接和传递依赖由 `services/deepseek-runtime/package-lock.json` 锁定；当前 Cordis 组合不装载通用 MCP Client。

官方来源：

- <https://github.com/deepseek-ai/deepseek-harness>
- <https://github.com/deepseek-ai/deepseek-harness/tree/master/python/sdk>
- <https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/sdk/protocol>
- <https://www.npmjs.com/package/@deepseek-ai/dsh-sdk-jsonrpc-demo>

官方 Python SDK 依赖 Pydantic `>=2.12`，平台当前依赖 Pydantic `2.11.3`。为避免把 SDK 依赖冲突带入 Agent API，平台自行维护最小 JSON-RPC 客户端，只把官方 Node Runtime 依赖装入独立 Harness 镜像。镜像通过 Node 22.19 构建阶段编译 `node-pty`，生产阶段只复制 Node Runtime 和锁定依赖，不保留编译工具。

116 预检发现 PyPI `deepseek-harness-runtime-bin==0.1.0rc6` 的 Linux x86_64 单文件载体在加载官方默认 `@deepseek-ai/dsh-subprocess-local` 时缺少 `pty.node`，JSON-RPC 初始化无法完成，因此该 wheel 不作为生产载体。切换到同版本官方 npm 包并现场编译原生依赖后，`initialize` 与 `shutdown` 协议握手均通过。平台随镜像提供与官方默认组合对齐的 `cordis.yml`，并关闭 DeepSeek 专用 thinking/reasoning 请求字段，使 Model Gateway 后面的普通 OpenAI Compatible 内网模型也能被路由；升级官方 Runtime 时必须重新做配置兼容检查。

## 2. 部署结构

```text
Agent API / Worker
        |
        | Bearer Runtime Key
        v
DeepSeek Security Gateway
        |--------------------------|
        |                          |
        | no credential            | inject Model Gateway Key
        v                          v
DeepSeek Harness Core       Model Gateway
        |
        | stdio JSON-RPC 2.0
        v
official dsh-jsonrpc-agent
```

Compose 中对应两个长期服务：

- `deepseek-runtime`：安全网关，对平台提供统一 HTTP Runtime 契约；
- `deepseek-harness-core`：官方 Harness 进程所有者，只加入隔离 Harness 网络。

平台控制网络和 Harness 执行网络分离。真实 `DEEPSEEK_RUNTIME_API_KEY` 与 `MODEL_GATEWAY_API_KEY` 只进入安全网关，不进入 Harness Core。Harness 只获得非敏感代理令牌；即使模型调用 bash 查看环境变量或 `/proc`，也不能读取真实平台密钥。Harness Core 也不能解析或直连 Agent API。

Harness Core 父进程只负责协议和进程管理。每个 repository Workspace 会分配独立的 Linux 数字 UID，Harness 子进程在启动前降权到该 UID，清空附加组，并把 repository 与 JSONL Session 目录设为该 UID 私有。父进程只保留 `CHOWN`、`DAC_OVERRIDE`、`FOWNER`、`SETGID`、`SETUID` 和 `KILL` 六项能力，用于移交目录、降权和终止对应进程组；其他 Linux capability 全部移除。不同 Agent/Session 的代码进程不能通过共享 Workspace 挂载读取或修改彼此的仓库。若 UID 分配、目录私有化或降权失败，执行直接失败，不退化为共享用户运行。

## 3. 平台统一契约

DeepSeek Adapter 对外实现：

- Session 创建；
- 同步执行；
- SSE 流式执行；
- Stop；
- Health；
- Runtime Registry/Router 选择；
- repository Workspace 校验；
- Trace 与 Artifact 归一化。

DeepSeek Agent 必须使用：

```json
{
  "runtime_type": "deepseek",
  "capability_profile": {
    "workspace_type": "repository",
    "required_tools": [],
    "artifact_types": ["code_patch", "git_diff", "test_report"]
  }
}
```

同步和流式完成事件都会保存 Runtime 产物。Git Patch 同时收集已跟踪修改与未跟踪新文件；测试输出只有在 Harness 实际观察到测试命令及结果时才生成 `test_report`。

## 4. Session 与重试语义

官方 Runtime 默认把 Session 持久化到 JSONL。平台 Memory 是跨 Runtime 的权威会话来源，执行 Prompt 已包含平台加载的历史消息。为避免失败重试时再次加载 Harness 内部旧历史并造成上下文重复，DeepSeek 的每次平台重试都会创建新的 Harness Runtime Session，但继续复用同一隔离 repository Workspace。

Runtime Session 会绑定 Agent、平台 Session、Workspace 和 Memory Namespace。相同 Runtime Session ID 如果携带不同 Workspace 身份会被拒绝。

## 5. 当前能力限制

- 当前固定的官方 `0.1.0-rc.6` SDK Cordis 组合没有装载通用 MCP Client，平台 MCP 绑定、权限与审计记录仍然保留，但不能声称已作为 Harness 原生 Tool 注入。
- Coding 执行目前使用官方内置 bash/filesystem。平台只把 `filesystem`、`database` 作为可验证的 MCP 必需能力；`git`、`terminal` 不伪装成已审计 MCP 能力。
- 官方项目处于 Developer Preview。升级 wheel 前必须重新核对 wire protocol、默认 Cordis 组合、Session 语义和安全隔离，并完整重跑验收。
- 代码修改和测试是否成功只能由真实 Coding Agent 端到端证据确认；Runtime Health 在线不能替代业务验收。

## 6. 116 验收要求

部署只能操作 Compose 项目 `hermes-agent-platform`，不得修改节点上的其他容器、网络和卷。验收至少包括：

1. 数据库迁移到 `0014_runtime_integration_layer`；
2. `deepseek-runtime` 与 `deepseek-harness-core` 健康；
3. Runtime Center 显示 DeepSeek `online`、版本 `0.1.0-rc.6`；
4. 创建 repository 类型 Coding Agent；
5. 同步执行产生代码修改、Coding Trace、Patch Artifact；
6. SSE 执行产生真实增量事件并持久化 Runtime Artifact；
7. Stop 能终止对应 Harness 进程并记录 cancelled；
8. 未跟踪新文件进入 Patch；
9. Harness Core 环境中不存在真实 Runtime Key 与 Model Gateway Key；
10. 非本项目容器 ID 在部署前后保持不变。

在以上真实端到端完成前，状态只能写“平台适配完成，116 部署未验证”。
