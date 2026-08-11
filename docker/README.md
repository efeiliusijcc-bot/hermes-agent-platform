# Docker 与离线部署目录

本目录保存镜像构建、导出、导入和离线部署相关文件。

Phase 0 不提供业务镜像，也不启动容器。基础服务定义从 Phase 1 开始加入。

116 节点上的所有命令必须显式使用项目名：

```bash
docker compose -p hermes-agent-platform ...
```
