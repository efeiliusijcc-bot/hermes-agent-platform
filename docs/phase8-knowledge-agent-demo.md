# Phase 8 Knowledge Analyst Demo

## 1. Demo 配置

Phase 8 提供一个长期存在、可通过 API 调用的 `knowledge-analyst`：

- Role：`企业知识分析专家`；
- Skill：`knowledge-analysis`；
- MCP：只读 `demo-filesystem-mcp` 与 `demo-database-mcp`；
- Knowledge Source：`company-docs`；
- 模型：116 节点现有的外部 OpenAI-compatible DeepSeek 路径。

Agent 配置保存在 `configs/knowledge-analyst-demo/agent.json`。Demo 数据分别落在：

- MinIO `knowledge` bucket：公司 AI 应用知识文档原文；
- PostgreSQL/pgvector：文档分片和向量；
- PostgreSQL `knowledge_agent_ai_metrics`：只读业务指标；
- `data/mcp-files/knowledge-agent-ai-operations.txt`：只读运维记录。

## 2. 可重复部署

在 116 的 `/opt/hermes-agent-platform` 中加载 `.env` 后执行：

```sh
./scripts/setup-knowledge-agent-demo.sh
```

脚本只替换以下 Demo 自有对象：

- Agent `knowledge-analyst`；
- MCP 注册项 `demo-filesystem-mcp`、`demo-database-mcp`；
- Knowledge Source `company-docs` 及其原文/向量；
- 表 `knowledge_agent_ai_metrics` 中的数据；
- 文件 `knowledge-agent-ai-operations.txt`。

已有且路径正确的 `knowledge-analysis` Skill 会直接复用。

## 3. 调用

```sh
curl -fsS -X POST http://127.0.0.1:18088/api/agents/knowledge-analyst/run \
  -H 'Content-Type: application/json' \
  --data '{"session_id":"operator-demo","input":"分析公司AI应用情况。"}'
```

## 4. 自动验收

```sh
./tests/phase8_knowledge_agent_demo.sh
```

测试会重新部署 Demo，并验证：

1. Role、Skill、两个 MCP 和 Knowledge Source 绑定完整；
2. Hermes/DeepSeek 真实执行并同时使用知识召回、文件和数据库证据；
3. 最终答案包含三类来源的独立验收标记；
4. `execution_logs` 记录 Skill、MCP、Knowledge 命中和两次成功工具调用；
5. 执行日志和回答中没有 MCP 能力令牌。

测试成功后保留 Demo，便于继续通过 API 调用。
