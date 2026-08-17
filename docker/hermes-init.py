import os
import pwd
from pathlib import Path

import yaml

home = Path("/opt/data")
home.mkdir(parents=True, exist_ok=True)
hermes_user = pwd.getpwnam("hermes")
home.chmod(0o700)
os.chown(home, hermes_user.pw_uid, hermes_user.pw_gid)

config = {
    "_config_version": 33,
    "model": {
        "default": os.environ["MODEL_NAME"],
        # The platform's model gateway is OpenAI-compatible and owns the
        # provider-specific credentials.  Hermes must treat it as a custom
        # endpoint; using the DeepSeek provider rewrites every Agent-level
        # model override to a DeepSeek canonical model.
        "provider": "custom",
        "base_url": "http://model-gateway:8080/v1",
        "api_key": os.environ["MODEL_GATEWAY_API_KEY"],
        "api_mode": "chat_completions",
    },
    "terminal": {
        "backend": "local",
        "cwd": "/opt/data",
        "timeout": 60,
        "home_mode": "auto",
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
temporary.chmod(0o600)
os.chown(temporary, hermes_user.pw_uid, hermes_user.pw_gid)
temporary.replace(home / "config.yaml")
