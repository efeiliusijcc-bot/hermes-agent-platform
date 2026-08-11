# Docker 与离线部署目录

本目录保存镜像构建、导出、导入和离线部署相关文件。

Phase 1 提供 PostgreSQL 16 + pgvector、Redis 7 和 MinIO。所有数据使用项目专属命名卷，服务仅连接项目内部网络，不发布宿主机端口。

116 节点上的所有命令必须显式使用项目名：

```bash
docker compose -p hermes-agent-platform ...
```
