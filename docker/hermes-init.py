import os
from pathlib import Path

import yaml

home = Path("/opt/data")
home.mkdir(parents=True, exist_ok=True)

config = {
    "_config_version": 12,
    "model": {
        "default": os.environ["MODEL_NAME"],
        "provider": "deepseek",
        "base_url": "http://model-gateway:8080/v1",
    },
    "terminal": {
        "backend": "local",
        "cwd": "/workspace",
        "timeout": 60,
        "home_mode": "workspace",
    },
    "memory": {
        "memory_enabled": False,
        "user_profile_enabled": False,
    },
    "agent": {
        "max_turns": 12,
        "verbose": False,
        "reasoning_effort": "low",
        "verify_on_stop": False,
    },
    "platform_toolsets": {"api_server": ["mcp-gateway"]},
    "updates": {"pre_update_backup": False},
    "plugins": {"enabled": []},
    "mcp_servers": {
        "mcp-gateway": {
            "url": "http://mcp-gateway:8090/mcp",
            "enabled": True,
            "connect_timeout": 30,
            "tools": {
                "include": ["filesystem_read", "database_query"],
                "prompts": False,
                "resources": False,
            },
        }
    },
}

temporary = home / "config.yaml.tmp"
temporary.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
temporary.replace(home / "config.yaml")
