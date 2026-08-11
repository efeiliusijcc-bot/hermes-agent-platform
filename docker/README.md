# Docker 与离线部署目录

本目录保存镜像构建、导出、导入和离线部署相关文件。

Phase 1 提供 PostgreSQL + pgvector、Redis 和 MinIO。持久数据写入项目专属的 `data/` 子目录，便于离线迁移并避免 Docker 卷清理导致数据丢失。服务仅连接项目内部网络，不发布宿主机端口。

Phase 3 的 Hermes Runtime 固定使用官方 `v2026.8.3`（Hermes Agent v0.20.0）镜像及不可变 digest，不使用会持续变化的 `latest` 标签。

首次启动前执行：

```bash
./scripts/prepare-data-dirs.sh
```

116 节点上的所有命令必须显式使用项目名：

```bash
docker compose -p hermes-agent-platform ...
```
