# 模型统一管理

## 1. 生效链路

模型管理不是前端展示表。控制台写入 `model_registrations`，Agent 保存的是模型 ID（别名），每次模型调用由 `model-gateway` 动态解析：

```text
Agent.model（模型 ID）
  -> model-gateway 查询 model_registrations
  -> 取得 Base URL、上游真实模型名、超时和重试配置
  -> 使用主密钥解密该模型的 API Key
  -> 按 OpenAI Compatible /chat/completions 调用上游
```

模型配置更新后不需要重启网关，下一次请求立即读取数据库中的新值。未注册或已停用的模型 ID 会被明确拒绝，不会被转发到任意地址。

## 2. 管理界面

访问控制台的“平台 → 模型管理”：

- 新增、编辑和删除模型配置；
- 启用或停用模型；
- 设置唯一默认模型；
- 轮换或清除单个模型的 API Key；
- 发起一次最多 8 token 的真实调用测试；
- 查看最近一次测试状态、时间和脱敏错误。

Agent 创建页和 Agent 详情配置页只允许选择注册表中的启用模型。模型 ID 是 Agent 使用的稳定别名，`upstream_model` 是发送给上游服务的真实模型名，两者可以不同。

## 3. 密钥边界

必须配置 `MODEL_REGISTRY_ENCRYPTION_KEY`。它是 Fernet 主加密密钥，仅提供给 `agent-api` 和 `model-gateway`；数据库只保存认证加密后的模型 API Key。

模型管理写操作由可信内网控制台直接调用，不使用浏览器认证 Header。内部 `MODEL_GATEWAY_API_KEY` 仍只用于运行时访问 Model Gateway，不能输入浏览器。模型读取接口只返回 `api_key_configured`，永不返回明文密钥或密文。日志、Trace 和 Artifact 也不得记录上述密钥。

生成缺失密钥：

```sh
./scripts/ensure-runtime-secrets.sh /opt/hermes-agent-platform/.env
```

脚本只写入权限为 `0600` 的 `.env`，不会在终端打印密钥值。

## 4. 兼容与迁移

首次升级到迁移 `0013_model_registry` 后，控制面会把现有 `MODEL_ENDPOINT`、`MODEL_NAME` 和 `MODEL_API_KEY` 安全登记为默认模型，并把已有 Agent 使用的其他模型名称登记为指向同一兼容端点的独立别名。已有 Agent 因此不需要手工改名；每个别名后续都可以在管理页改成自己的地址、真实模型名和密钥。

环境变量配置只作为迁移期的单模型回退：

- 数据库可用时，注册表是权威配置；
- 注册表暂时不可用时，只允许回退到原 `MODEL_NAME`；
- 其他模型 ID 不会在数据库故障时被猜测或转发。

不要直接更换 `MODEL_REGISTRY_ENCRYPTION_KEY`。数据库中已有密文时更换主密钥会导致无法解密；如确需更换，应先制定密钥重加密迁移，或逐项重新录入模型 API Key。

## 5. 管理 API

只读接口不返回密钥：

- `GET /api/models`
- `GET /api/models/{model_id}`

以下写操作不要求浏览器侧解锁凭据：

- `POST /api/models`
- `PATCH /api/models/{model_id}`
- `POST /api/models/{model_id}/default`
- `POST /api/models/{model_id}/test`
- `DELETE /api/models/{model_id}`

编辑时不提交 `api_key` 表示保留原密钥；提交新值表示轮换；`clear_api_key=true` 表示清除。默认模型不能直接停用或删除，仍被 Agent 使用的模型也不能删除。

## 6. 116 升级验证

Docker 构建与 Compose 验证只在 116 节点执行：

```sh
cd /opt/hermes-agent-platform
./scripts/ensure-runtime-secrets.sh .env
docker compose -p hermes-agent-platform build agent-api frontend
docker compose -p hermes-agent-platform up -d --wait model-gateway agent-api agent-worker hermes-orchestrator frontend
docker compose -p hermes-agent-platform exec -T agent-api alembic current
./tests/model_registry.sh
```

预期迁移头为 `0013_model_registry (head)`。验收至少包括：只读接口不含任何密钥字段、无模型专用管理 Header 可完成 CRUD、模型真实调用测试在线、Agent 同步与 SSE 各完成一次，以及修改上游模型名后网关确实使用新值。
