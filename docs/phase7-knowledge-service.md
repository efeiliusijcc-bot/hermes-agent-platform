# Phase 7 Knowledge Service 设计与验收

## 1. 服务边界

`knowledge-service` 是仅连接 `platform-internal` 网络的独立容器，不发布宿主机端口。职责包括：

- 校验并解析上传文档；
- 文本切片；
- 生成离线 Embedding；
- 把原始文件存入 MinIO `knowledge` bucket；
- 把文档元数据与 384 维向量写入 PostgreSQL/pgvector；
- 按指定 Knowledge Source 执行余弦向量检索；
- 删除 Source 时清理 MinIO 原文和数据库记录。

`agent-api` 负责 Source CRUD、Agent 绑定和上传/搜索接口代理。Hermes Runtime 不直接访问 Knowledge Service，运行前由 Agent API 根据当前 Agent 的绑定完成检索并注入召回片段。

## 2. 数据模型

- `knowledge_sources`：Source 配置和状态。
- `knowledge_documents`：文件名、类型、SHA-256、MinIO object key、解析器和分片数。
- `knowledge_chunks`：文本分片、384 维 `vector`、分片元数据。
- `agent_knowledge`：Agent 与 Source 的多对多绑定。

`knowledge_chunks.embedding` 使用 pgvector `vector(384)`，并创建 cosine HNSW 索引。

## 3. 文档安全边界

支持：Markdown、UTF-8 文本、PDF、Word `.docx`、Excel `.xlsx`。

- 上传大小、抽取字符数、PDF 页数、Excel 单元格数均有上限；
- Office ZIP 包限制条目数和解压后总大小；
- 空文档、无可抽取文本、格式不匹配和不支持扩展名直接拒绝；
- 同一 Source 内按 SHA-256 拒绝重复内容；
- MinIO object key 使用 Source ID、服务端 UUID 和安全文件名构造。

## 4. 离线 Embedding

第一阶段使用确定性的 `hash-ngram-v1`：对 Unicode 规范化后的词、字符 1/2/3-gram 做带符号特征哈希并 L2 归一化，输出 384 维向量。该算法：

- 完全离线，不调用 LLM 或外部 Embedding API；
- 中英文使用同一确定性逻辑；
- 文档和查询算法一致，可审计、可复现；
- 通过独立 Knowledge Service 封装，后续可在不改变 Agent/Source/RAG 流程的前提下替换为内网 Embedding 模型。

## 5. Agent 运行时

运行顺序：

```text
用户问题
  -> 查询当前 Agent 的 active Knowledge Source 绑定
  -> Knowledge Service 向量检索
  -> 召回片段作为不可信资料 JSON 注入
  -> Hermes + 模型生成答案
  -> execution_logs 记录 source/document/chunk ID 与 score
```

执行日志不保存召回正文，也不保存 MinIO 或数据库密钥。

## 6. API

- `POST /api/knowledge-sources`
- `GET /api/knowledge-sources`
- `GET /api/knowledge-sources/{id}`
- `DELETE /api/knowledge-sources/{id}`
- `POST /api/knowledge-sources/{id}/documents`
- `GET /api/knowledge-sources/{id}/documents`
- `POST /api/knowledge-sources/{id}/search`
- `GET /api/agents/{id}/knowledge-sources`
- `PUT /api/agents/{id}/knowledge-sources/{source_id}`
- `DELETE /api/agents/{id}/knowledge-sources/{source_id}`

`POST /api/agents/{id}/run` 自动检索当前 Agent 已绑定的 active Source。

## 7. 116 验收

只在 `/opt/hermes-agent-platform`、Compose 项目 `hermes-agent-platform` 内构建和运行：

```sh
./tests/phase7_knowledge_service.sh
```

自动验证 Markdown/PDF/Word/Excel 解析、重复内容拒绝、MinIO 原文、384 维 pgvector、向量搜索、Agent 召回、日志摘要、绑定级联和对象清理。
