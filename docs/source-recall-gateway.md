# Source Recall Gateway

`source-recall-gateway` 是平台内唯一负责调用外部或内网信源召回服务的受控适配层。Skill 不保存接口地址和密钥，也不能直接发起 HTTP 请求。

## 网络边界

- `agent-worker`、`hermes-runtime`、`hermes-orchestrator` 仅加入 `platform-internal`。
- `source-recall-gateway` 同时加入 internal 与 edge 网络，但不映射宿主机端口。
- Agent 通过内部 Bearer Key 调用网关；上游密钥只注入网关容器。
- 在完全隔离环境中，`SOURCE_RECALL_UPSTREAM_ENDPOINT` 必须替换为容器可访问的内网地址或内网 DNS。

## 配置

在部署环境的 `.env` 中配置，禁止提交真实密钥：

```dotenv
SOURCE_RECALL_ENABLED=true
SOURCE_RECALL_GATEWAY_ENDPOINT=http://source-recall-gateway:8082
SOURCE_RECALL_GATEWAY_API_KEY=<内部随机密钥>
SOURCE_RECALL_UPSTREAM_ENDPOINT=<内网召回接口>
SOURCE_RECALL_UPSTREAM_API_KEY=<上游召回密钥>
SOURCE_RECALL_UPSTREAM_TIMEOUT_SECONDS=60
SOURCE_RECALL_UPSTREAM_MAX_RETRIES=1
```

## Skill 触发

只有 `config.yaml` 声明以下配置的 Skill 才触发召回：

```yaml
source_recall:
  enabled: true
  lookback_days: 3650
  limit: 20
```

平台把 `parameters.topic` 作为首选查询主题，没有该字段时才使用原始请求文本。上游响应中的来源正文按字符上限裁剪后注入，完整密钥不会进入 Execution、Trace 或 Artifact。

## 失败关闭

- 上游不可用、超时、未配置或返回非法结构时，平台注入“召回不可用”状态，Skill 应返回 `blocked`。
- `status=fallback` 或 `diagnostics.retrieverErrors` 非空不等同于召回失败，但必须逐条校验相关性并在 `information_gaps` 披露降级。
- 返回 HTTP 200、非空来源或较高分数都不能替代主题相关性检查。

## 验收

至少验证：网关健康、真实请求、无关主题 `blocked`、相关主题 `completed`、Sync、SSE Stream、Output Schema、Execution Trace、Session/Workspace、`result.json` 与 `report.md` 下载校验，以及 Worker/Runtime 直接公网访问失败。
