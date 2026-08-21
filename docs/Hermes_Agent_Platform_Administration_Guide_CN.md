# Hermes Agent Platform 平台管理使用手册

面向平台管理员的配置、验证和故障排查指南。所有示例均为内网占位值，不包含真实凭据或生产地址。

更新日期：2026-08-20

## 首次配置推荐顺序

1. **配置模型**：登记模型别名、Provider、Adapter、上游模型名和访问凭据，并完成连接测试。
2. **检查运行时**：确认 Hermes、Pi 或 DeepSeek Runtime 在线，并与目标 Agent 的运行方式匹配。
3. **发布连接与能力**：创建凭据、Connector、Operation 和 Capability，测试后发布不可变版本。
4. **配置数据库范围**：连接 PostgreSQL，发现资源，并为每个数据库创建最小只读 Scope。
5. **建立 API 授权**：创建 Client 和一次性 Key，绑定允许调用的 Agent 与 API 版本。
6. **验证平台状态**：在 Operations 和 Settings 检查调用指标、Runtime、数据服务与 Artifact 存储。

## 统一术语表

| 术语 | 通俗解释 |
| --- | --- |
| Agent 模型别名 | Agent 配置中保存的稳定模型 ID，用于查找模型注册记录，不等于上游服务要求的真实模型名。 |
| Provider | 模型服务提供方或兼容类型，例如 Qwen、DeepSeek、OpenAI Compatible 或自定义服务。 |
| Adapter | 平台把统一模型请求转换为特定 Runtime 或 Provider 协议的适配层。 |
| Runtime | 真正执行 Agent 的运行环境，例如 Hermes、Pi 或 DeepSeek Harness。Runtime 不是模型。 |
| Connector | 一类外部系统的连接器定义，例如 Internal REST、MCP 或 PostgreSQL MCP。 |
| Instance | Connector 的一个实际部署或连接目标，例如测试环境的知识检索服务。 |
| Revision | Instance 或 Scope 的不可变配置快照。修改配置会生成新 Revision，历史执行仍引用旧版本。 |
| Operation | Connector 可执行的具体动作，例如 source_search 或 db_select。 |
| Capability | 提供给 Agent 的抽象业务能力，例如 knowledge.search，不直接暴露真实 Endpoint。 |
| Implementation | Capability 与某个 Connector Operation 之间的可执行映射。 |
| Credential | 平台加密托管的用户名、密码或 API Key。模型、Agent 输出和普通接口不会得到明文。 |
| Resource Scope | Agent 可访问资源的冻结范围，例如指定数据库中的 Schema、Table 和 View。 |
| Schema Version | 生产 API 输入和输出 JSON Schema 的不可变版本。 |
| API Version | 对外调用契约版本，它绑定一个 Schema Version，并与 Agent 的内部版本分开管理。 |

## 状态说明

| 状态 | 含义 | 建议操作 |
| --- | --- | --- |
| READY / healthy / online | 配置完整且当前检查通过，可以继续发布或运行。 | 仍应做一次目标 Agent 的真实最小调用。 |
| NEEDS_CONFIGURATION | 对象存在，但缺少凭据、Scope、实现或其他必填配置。 | 打开详情，根据缺失项补齐后重新测试。 |
| UNAVAILABLE / unhealthy / offline | 目标服务无法访问、认证失败或运行时离线。 | 按网络、凭据、服务健康、配置版本的顺序排查。 |
| degraded | 主流程仍可能运行，但部分依赖或能力不可用。 | 查看技术详情和 Trace，不要把降级当作完整验收通过。 |
| disabled / deprecated | 已停用或进入淘汰期，不应再用于新绑定。 | 迁移到新版本；保留历史引用，不原地覆盖。 |

## 模型管理

菜单路径：平台管理 > 模型管理

### 用途

统一登记 Agent 实际调用的模型服务。Agent 只保存模型 ID，Model Gateway 在执行时解析真实地址、上游模型名和加密 API Key。

### 使用前准备

- 准备可从平台容器访问的模型 Base URL。
- 确认上游模型名和接口兼容协议。
- 如服务要求认证，准备独立 API Key。

### 字段说明

| 字段 | 含义 | 推荐配置 |
| --- | --- | --- |
| 模型 ID | 平台内稳定别名，Agent 通过它选模型。创建后尽量不改。 | 使用用途明确的英文短名，例如 report-main。 |
| Provider | 模型服务提供方或兼容类型。 | 按真实协议选择，不按模型宣传名称猜测。 |
| Adapter | 平台请求的协议转换方式。 | 选择与当前 Runtime 和上游接口都兼容的 Adapter。 |
| Base URL | 上游模型 API 根地址。 | 容器间访问填写服务名，例如 http://model-gateway:8000；不要填 127.0.0.1 指向其他容器。 |
| 上游模型名 | 发送给模型服务的真实 model 值。 | 严格使用提供方返回或文档声明的名称。 |
| API Key | 上游访问凭据，加密保存且永不回显。 | 按服务独立分配；修改时留空表示保留原值。 |
| 默认模型 | 未显式选模型时的平台默认项。 | 只保留一个经过真实调用验证的默认模型。 |
| 超时 / 重试 | 单次请求等待时间和安全重试次数。 | 普通对话 60-180 秒；长报告按实测增加。重试建议 1-2 次。 |

### 操作步骤

1. 点击“新增模型”，填写模型 ID、Provider、Adapter、Base URL 和上游模型名。
2. 录入或轮换 API Key，保存后确认页面只显示“已配置”或脱敏状态。
3. 执行连接测试，确认协议、认证和模型名都通过。
4. 将已验证模型设为默认项，或在 Agent 构建页明确选择该模型 ID。
5. 运行一个最小 Agent 请求，并在执行详情中确认实际模型别名和结果。

### 成功标准

- 连接测试成功。
- API 响应、日志和 Trace 不出现 API Key。
- 目标 Agent 完成一次真实模型调用。

### 常见错误

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| 模型名存在但调用返回 404 | 上游模型名或 Base URL 路径不正确。 | 用上游服务的模型列表或文档核对真实 model 值，注意它不是平台模型 ID。 |
| 401 / 403 | API Key 无效、未配置或没有模型权限。 | 轮换凭据后重新测试，检查 Key 对应账号权限。 |
| 502 / timeout | 上游服务不可达、代理链异常或超时过短。 | 先从调用容器验证 DNS 和端口，再查上游健康与超时配置。 |

### 安全注意事项

- Agent 模型别名不等于上游真实模型名。
- API Key 不得写入 Agent Prompt、Skill、日志或导出包。
- 模型配置变化会影响后续调用，修改前先确认使用它的 Agent。

## 运行时管理

菜单路径：平台管理 > 运行时管理

### 用途

查看 Hermes、Pi 和 DeepSeek Harness 的注册实例、版本、健康状态、特性支持和 Agent 使用关系。

### 使用前准备

- Runtime 服务已由部署人员启动。
- Runtime 地址能从 agent-api 和 Worker 所在网络访问。
- 至少一个模型注册记录可用。

### 字段说明

| 字段 | 含义 | 推荐配置 |
| --- | --- | --- |
| Runtime 类型 | Hermes、Pi 或 DeepSeek 的执行引擎。 | 按 Agent 所需工具协议和能力选择。 |
| 实例 / 版本 | 实际运行服务及其版本标识。 | 生产 Agent 绑定经过契约测试的固定版本。 |
| 健康状态 | 控制面探测 Runtime 是否可连接并可执行。 | 发布 Agent 前必须为 online 或 healthy。 |
| Feature Profile | Runtime 支持的流式、工具调用、Capability Gateway 等特性。 | Preflight 必须与 Agent 所需特性完全匹配。 |
| Agent 使用数 | 当前绑定此 Runtime 的 Agent 数量。 | 变更或下线前先确认影响范围。 |

### 操作步骤

1. 点击“检查全部”，确认目标 Runtime 在线。
2. 查看版本和 Feature Profile 是否满足 Agent 的流式与工具调用需求。
3. 确认 Agent 使用关系，避免误停正在使用的实例。
4. 在 Agent 构建页选择 Runtime，并执行 Preflight。
5. 运行最小任务，在 Trace 中确认请求进入预期 Runtime。

### 成功标准

- 健康检查为 online。
- Feature Profile 与 Agent 需求兼容。
- 最小任务在正确 Runtime 完成。

### 常见错误

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| Runtime offline | 服务未启动、地址错误或网络不通。 | 检查容器状态、服务健康端点和 Docker 网络。 |
| 请求返回 502 | 平台能访问适配层，但适配层无法完成下游调用。 | 查看 Runtime 容器日志和下游模型连接，不要只重试前端。 |
| Preflight 提示特性不兼容 | Agent 需要的工具或流式能力未在 Feature Profile 中验证。 | 选择支持该特性的 Runtime，或先完成契约测试再启用。 |

### 安全注意事项

- Runtime 与模型是两层：Runtime 负责编排执行，模型负责生成。
- Execution Token 只应存在于 Worker 和内部请求中。
- 不要在 Runtime 环境变量、Prompt 或工具参数中放数据库密码。

## 连接与能力

菜单路径：平台管理 > 连接与能力

### 用途

把真实 REST 或 MCP 接口转换成 Agent 可安全绑定的抽象 Capability，并统一管理加密凭据、版本和健康状态。

### 使用前准备

- 目标接口可从平台内部网络访问。
- 已取得接口 Schema、认证方式和安全边界。
- 明确该接口属于只读、安全重试还是高风险写操作。

### 字段说明

| 字段 | 含义 | 推荐配置 |
| --- | --- | --- |
| Connector | 连接器类型定义。 | 首版使用 internal_rest 或 mcp。 |
| Instance | 一个实际接口环境。 | 测试和生产分别建 Instance，不共用凭据。 |
| Revision | Endpoint、网络区和认证引用的不可变快照。 | 变更地址或认证后创建新 Revision。 |
| Operation | HTTP 方法与路径，或 MCP Tool。 | 每个 Operation 只表达一个明确动作。 |
| Capability | Agent 使用的抽象能力名称。 | 采用 namespace.key 和 SemVer，例如 knowledge.search@1.0.0。 |
| Implementation | Capability 到 Operation 的映射。 | 发布前确认输入输出 Schema 和失败策略。 |
| Credential | 加密保存的 API Key 或认证数据。 | 只通过 credential_ref 引用，不放进 Revision JSON。 |
| 风险等级 | 调用可能造成的数据或系统影响。 | 查询类用 LOW；写入、外发或不可逆操作提高等级并要求审批。 |

### 操作步骤

1. 先在“凭据”页创建 Credential，确认只显示脱敏标签。
2. 创建 Connector Instance，填写内网 Endpoint、认证方式和 credential_ref。
3. 测试连接，确认 DNS、协议和认证正常。
4. 定义 Operation 的业务输入与输出 JSON Schema。
5. 创建 Capability Version 和 Implementation，完成测试后发布。
6. 在 Agent Builder 中绑定 Capability 和 Resource Scope，再执行 Preflight。

### 成功标准

- Connector 健康状态为 READY。
- Capability 已发布且 Agent Preflight 无缺失项。
- Trace 中可看到授权、连接调用和标准化结果，且无明文凭据。

### 常见错误

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| 连接测试失败但地址在宿主机可访问 | 容器网络与宿主机网络不同。 | 从实际调用容器检查 DNS 和端口，使用容器服务名。 |
| Capability 显示 NEEDS_CONFIGURATION | 缺少 Implementation、Credential、Scope 或已发布版本。 | 根据详情逐项补齐并重新发布。 |
| Runtime 看不到工具 | Agent 未绑定、Alias 冲突、Snapshot 仍是旧版本或 Runtime 不支持。 | 重新 Preflight 和发布 Agent，核对 resolution_digest 与 Feature Profile。 |

### 安全注意事项

- 模型不能提交 Endpoint、Credential ID、Implementation ID 或 Scope ID。
- 已发布 Capability Version 和 Revision 不可原地覆盖。
- 非幂等写操作不得自动重试。

## 数据库连接

菜单路径：平台管理 > 数据库连接

### 用途

连接内网 PostgreSQL、MySQL、MariaDB、Doris、StarRocks、SQL Server、Oracle、达梦 DM、ClickHouse、Elasticsearch 或 SQLite，发现可访问资源，并为 Agent 创建最小只读数据范围。各类型的验证状态和驱动要求见 `docs/multi-database-connection.md`。

### 使用前准备

- `agent-database-mcp` 容器已加入目标数据库所在 Docker 网络；SQLite 文件已放入 `data/database-files/`。
- 准备具有最小只读权限的数据库账号。PostgreSQL 还需 CONNECT 权限；Elasticsearch 还需文档规定的只读发现权限。
- 达梦环境已提供与目标 CPU 架构和 Python 3.12 匹配的官方 `dmPython` 驱动。

### 字段说明

| 字段 | 含义 | 推荐配置 |
| --- | --- | --- |
| 数据库类型 | 连接所使用的协议和 SQL 方言。 | 创建后不可原地更换；需要更换时创建新连接。 |
| 主机 | 目标数据库在容器网络中的 DNS 名称。 | 填写目标容器名或内网主机名；不要填写 127.0.0.1。 |
| 端口 | 目标数据库实际监听端口。 | 使用类型默认端口或目标环境实际端口，不要求暴露宿主机端口。 |
| 维护库 | 用于初始登录和资源发现的数据库。 | 按数据库类型默认值填写；账号必须能访问。 |
| SSL 模式 | 数据库连接的 TLS 策略。 | 完全隔离内网可按部署策略使用 disable；跨受控网络按数据库要求配置。 |
| 用户名 / 密码 | 数据库登录凭据，加密托管。 | 使用专用只读账号，不复用管理员账号；SQLite 不需要凭据。 |
| Schema / Table / View | 数据库内可选择的数据资源层级。 | 只勾选任务所需资源，优先授权 View。 |
| Scope | 固定一个数据库及允许资源与限制的不可变范围。 | 按 Agent 或业务用途拆分 Scope。 |
| 最大行数 / 超时 / 配额 | 单次查询和每分钟调用的资源限制。 | 预览 20-50 行，常规查询不超过 200 行；超时从 5-15 秒起。 |

### 操作步骤

1. 部署人员将 `agent-database-mcp` 容器加入目标数据库网络，或将 SQLite 文件放入平台数据库文件目录。
2. 打开创建向导，先选择数据库类型，再填写主机、端口、维护库、SSL、用户名和密码。
3. 执行临时测试，确认 DNS、TCP、认证、SELECT 1 和只读检查通过。
4. 读取数据库资源树，选择数据库及允许的 Schema、Table 或 View。
5. 为每个数据库分别设置最大行数、超时和每分钟配额并保存 Scope Revision。
6. 在 Agent Builder 中绑定所需 Scope 和工具子集，发布后执行真实只读查询。

### 成功标准

- 测试返回 READY，并展示数据库资源树。
- Agent A 只能查询其 Scope 内资源，不能复用 Agent B 的范围。
- 写 SQL、跨 Scope SQL、超时和超大结果均被拒绝。

### 常见错误

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| 主机解析失败 | `agent-database-mcp` 未加入目标网络，或填写了错误容器名。 | 由部署人员连接 Docker 网络，并用 docker inspect 核对网络和容器名。 |
| Elasticsearch 权限不足 | 账号缺少资源发现所需只读权限。 | 增加 cluster monitor，以及目标索引的 read、view_index_metadata、monitor。 |
| 达梦驱动未安装 | 镜像中没有匹配目标平台的官方 dmPython。 | 将厂商 wheel 和必需原生库放入 drivers/dm 后重新构建数据库 MCP 镜像。 |
| 未再次填写密码也能测试已保存连接 | 平台使用之前加密保存的托管凭据。 | 这是正常行为，并非无凭据访问；需要换密码时使用凭据轮换。 |
| 认证成功但看不到部分数据库 | 账号没有目标数据库 CONNECT 或 Schema USAGE 权限。 | 由数据库管理员补充最小只读权限，再重新发现。 |
| 查询被安全策略拒绝 | SQL 含写 CTE、锁、危险函数、多语句或跨 Scope 表。 | 改为单条纯 SELECT，并限制在已授权表或视图中。 |

### 安全注意事项

- 模型看不到数据库地址、用户名、密码、Connection ID 或 Credential ID。
- 数据库账号只读与 `agent-database-mcp` SQL AST 拦截必须同时保留。
- 连接停用或凭据轮换后应立即失效旧连接池。

## API Center

菜单路径：平台管理 > API Center

### 用途

为内网业务系统创建 API Client、一次性 Key 和 Agent 调用授权，并管理稳定的 Schema Version 与 API Version。

### 使用前准备

- 目标 Agent 已发布且完成真实运行验证。
- 已定义生产输入和输出 JSON Schema。
- 明确调用方、负责人、频率和允许调用的 Agent。

### 字段说明

| 字段 | 含义 | 推荐配置 |
| --- | --- | --- |
| API Client | 一个调用系统或业务方的身份。 | 按系统分配，不多人共用一个 Client。 |
| 一次性 Key | 创建时仅显示一次的调用密钥。 | 立即保存到调用方的安全配置，遗失后轮换。 |
| 限流 | Client 每分钟允许的请求数量。 | 从业务实测低值开始，结合模型和 Worker 容量调整。 |
| Agent 授权 | Client 可以调用的 Agent 白名单。 | 只授权确有业务需要的已发布 Agent。 |
| Schema Version | 输入输出 JSON Schema 的不可变版本。 | 破坏性字段变更创建新版本。 |
| API Version | 对外路径或契约版本，绑定 Schema Version。 | 旧调用方迁移完成前保留旧版本。 |
| Sync / Stream | 同步完整响应或 SSE 流式输出模式。 | 短任务用 Sync，长生成任务优先 Stream。 |

### 操作步骤

1. 创建 API Client，填写清晰的系统名称、负责人和限流。
2. 生成 Key，并立即复制到调用方安全配置；页面关闭后不能取回。
3. 为 Client 绑定允许调用的已发布 Agent。
4. 创建不可变 Schema Version，并绑定 API Version。
5. 分别执行 Sync 和 Stream 最小调用，核对状态码、Schema、限流和 Trace。
6. 在 Operations 查看实际调用指标和错误率。

### 成功标准

- 未授权 Agent 返回权限错误。
- 有效 Key 可调用授权 Agent，输出符合绑定 Schema。
- 超出配额时返回明确限流错误且不会进入模型执行。

### 常见错误

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| Key 关闭弹窗后无法查看 | 明文只显示一次，这是设计行为。 | 创建新 Key 并撤销旧 Key。 |
| 403 未授权 | Client 未绑定该 Agent，或 Agent 未发布。 | 检查 Client 授权和 Agent 生命周期状态。 |
| 输出 Schema 校验失败 | Agent 输出与 API Version 绑定的 Schema 不一致。 | 修正 Agent 输出或发布新的 Schema/API Version，不覆盖旧版本。 |

### 安全注意事项

- Key 明文只显示一次，接口和日志不得回显。
- 限流是容量和滥用保护，不等于用户级 RBAC。
- Client 授权应遵循最小 Agent 白名单。

## Operations

菜单路径：平台管理 > Operations

### 用途

查看调用指标、Agent 运行表现、Runtime Health 和基础设施状态，用于验收配置和确定故障所在层级。

### 使用前准备

- 控制面健康接口可访问。
- 系统已有至少一次 Agent 执行，才能产生有意义的调用指标。

### 字段说明

| 字段 | 含义 | 推荐配置 |
| --- | --- | --- |
| 累计调用 / 错误数 | 平台记录的调用总量与失败量。 | 结合时间范围和具体 Execution 判断，不单看累计值。 |
| 平均延迟 | 调用耗时的聚合值。 | 进一步按模型、Runtime 和 Connector 拆分定位。 |
| Runtime Health | 模型、Worker、MCP 和 Skill 的聚合健康。 | degraded 时查看具体 Agent 健康详情。 |
| 基础设施状态 | PostgreSQL、Memory、Knowledge、Queue 和 Artifact Storage 状态。 | 任何核心组件 unhealthy 都应先处理再测 Agent。 |

### 操作步骤

1. 点击“重新检查”获取当前状态。
2. 先查看基础设施，再看 Runtime，再看 Agent 指标。
3. 从失败 Agent 打开 Execution 详情，确认错误发生在哪个节点。
4. 进入 Trace 查看模型、Capability、Connector 和 Artifact 事件。
5. 修复后使用同一最小输入重测，并比较前后状态。

### 成功标准

- 核心基础设施为 healthy。
- 目标 Runtime online，错误率和延迟符合当前验收目标。
- 失败可通过 Execution 和 Trace 定位到具体层级。

### 常见错误

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| 页面显示 unknown | 健康数据未返回、尚无 Agent 检查或接口异常。 | 刷新后检查控制面健康接口和具体组件日志。 |
| 控制面 healthy 但 Agent 失败 | 基础服务在线不代表模型、凭据、Scope 或业务输出正确。 | 继续查看 Agent Health、Execution 和 Trace。 |
| 错误率升高 | 可能来自模型、Runtime、Connector、限流或输入校验。 | 按失败状态码和 Trace 节点分类，不直接归因。 |

### 安全注意事项

- Operations 只展示运行状态，不应展示业务正文或凭据。
- healthy 只表示探测通过，不等于端到端业务验收通过。

## Settings

菜单路径：平台管理 > Settings

### 用途

只读展示平台运行边界、数据服务、Artifact 存储和密钥策略。实际基础设施配置由服务端环境变量和 Compose 管理。

### 使用前准备

- 控制面健康接口可访问。
- 部署人员已完成服务端环境变量和存储配置。

### 字段说明

| 字段 | 含义 | 推荐配置 |
| --- | --- | --- |
| 运行模式 | Sync JSON、SSE Stream 和 Async Queue 的可用状态。 | 按 Agent 场景选择，不在本页直接修改。 |
| 数据服务 | PostgreSQL、Memory、Knowledge 和 Task Queue 的当前健康。 | 出现异常后到 Operations 和服务端进一步排查。 |
| Artifact 存储 | 产物保存、受控下载、大小和 SHA-256 完整性信息。 | 离线部署后做一次上传、下载和哈希比对。 |
| 安全边界 | 哪些配置由前端管理，哪些只能由部署环境管理。 | 主密钥、内部服务密钥和 Docker 网络不得由浏览器配置。 |

### 操作步骤

1. 点击“刷新状态”。
2. 确认控制面、数据库、Memory、Knowledge、Queue 和 Artifact Storage 状态。
3. 如模型需变更，前往模型管理；如连接需变更，前往对应连接页面。
4. 基础设施地址、主密钥或 Compose 参数由部署人员在服务器维护。
5. 完成一次 Artifact 下载并核对 size 与 SHA-256。

### 成功标准

- 页面状态与 Operations 一致。
- Artifact 可下载且完整性一致。
- 前端不读取或回显服务端主密钥。

### 常见错误

| 现象 | 常见原因 | 处理方法 |
| --- | --- | --- |
| 找不到编辑按钮 | 该页主要是只读边界和状态说明。 | 按字段跳转到模型、连接页面，或由部署人员修改服务端配置。 |
| Artifact Storage unhealthy | 对象存储、挂载目录或访问配置异常。 | 先检查存储服务和挂载，再执行上传下载验证。 |
| 刷新后状态仍旧 | 后端健康检查未更新或依赖仍未恢复。 | 在 Operations 查看详细状态，并检查对应服务日志。 |

### 安全注意事项

- Fernet 主密钥、Model Gateway 内部密钥和数据库密码不能进入前端。
- Settings 状态页不是宿主机或 Docker 管理入口。
- 离线环境仍需保留 Agent、Scope、凭据和审计隔离。

## 常见场景

### 新建一个可聊天 Agent

1. 先完成模型连接测试。
2. 确认目标 Runtime online。
3. 创建 Agent 并选择模型别名与 Runtime。
4. Preflight、发布并在聊天页完成两轮上下文验证。

### 让不同 Agent 使用不同接口

1. 为每个接口建立 Connector Operation 和 Capability。
2. 为 Agent 分别绑定 Capability、Scope、Quota 和 Tool Alias。
3. 发布后用 Trace 核对实际调用的 Binding 和 Connector Revision。

### 接入一台 PostgreSQL 服务器

1. 由部署人员连接 agent-database-mcp 与数据库 Docker 网络。
2. 通过向导测试凭据并发现数据库树。
3. 按数据库分别创建最小 Scope。
4. 绑定 Agent 后验证允许查询和越权拒绝。

## 故障定位顺序

1. 先确认输入、Agent 生命周期和 Preflight 结果。
2. 检查 Operations 中的基础设施和 Runtime Health。
3. 打开 Execution 详情确认失败节点和标准错误码。
4. 查看 Trace 中的模型、Capability、Connector、Scope 和 Artifact 事件。
5. 从实际调用容器验证 DNS、端口和目标服务健康。
6. 使用相同最小输入复测，并保留修复前后的 Execution ID。

## 安全边界总览

- 浏览器和模型都不能读取明文模型 Key、数据库密码或 Connector Credential。
- 模型只能提交业务参数，不能选择 Endpoint、Credential、Implementation 或 Scope。
- Revision、Scope Revision、Schema Version 和已发布 Capability Version 不可原地覆盖。
- Docker 网络、主密钥、内部服务密钥和宿主机配置由部署人员维护。
- 完全隔离内网不代表可以取消最小权限、只读 SQL、配额、审计和 Agent 隔离。
