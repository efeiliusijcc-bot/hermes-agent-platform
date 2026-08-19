from __future__ import annotations

import os


os.environ.setdefault("POSTGRES_USER", "gateway-test")
os.environ.setdefault("POSTGRES_PASSWORD", "gateway-test-password")
os.environ.setdefault("POSTGRES_DB", "gateway-test")
os.environ.setdefault("REDIS_PASSWORD", "gateway-test-redis-password")
