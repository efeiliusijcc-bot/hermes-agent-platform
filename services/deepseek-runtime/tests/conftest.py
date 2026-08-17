from __future__ import annotations

import os
import sys
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))
os.environ["DEEPSEEK_RUNTIME_API_KEY"] = "test-deepseek-runtime-key-long-enough"
os.environ["MODEL_GATEWAY_API_KEY"] = "test-model-gateway-key-that-is-long-enough"
os.environ.setdefault("WORKSPACE_ROOT", "/tmp/hermes-deepseek-runtime-tests/workspaces")
os.environ.setdefault("DEEPSEEK_SESSION_ROOT", "/tmp/hermes-deepseek-runtime-tests/sessions")
