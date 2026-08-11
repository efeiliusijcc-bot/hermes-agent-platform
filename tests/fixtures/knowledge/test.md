# 北辰计划离线知识说明

北辰计划采用 Hermes Agent Runtime、Knowledge Service 与 PostgreSQL pgvector 构建内网知识检索链路。

部署要求：所有组件在 116 测试节点通过 `hermes-agent-platform` Compose 项目运行，模型由内网 OpenAI-compatible 接口提供。

项目结论：文档解析、离线 Embedding、向量召回和 Agent 上下文注入已经形成可审计闭环。

验收标记：POLARIS_KNOWLEDGE_SIGNAL_27
