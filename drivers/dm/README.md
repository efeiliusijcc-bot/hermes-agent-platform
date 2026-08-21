# 达梦 DM 官方驱动放置目录

将与目标 Linux CPU 架构和 Python 3.12 匹配的达梦官方 `dmPython` wheel
及其必需的原生库放在本目录，再构建 `postgres-mcp` 镜像。

达梦驱动不从 PyPI 拉取，平台也不在仓库中分发厂商授权文件。
如果未提供驱动，连接测试会明确返回“达梦 dmPython 官方驱动未安装”。
