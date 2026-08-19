from __future__ import annotations

import hashlib
import sys
from pathlib import Path


EXPECTED_SHA256 = "4c12f84662711cc14b6d52ba8d89156d1ad8a1ed22af100104a67d1520333ff6"


def replace_once(source: str, old: str, new: str) -> str:
    if source.count(old) != 1:
        raise RuntimeError(f"Hermes API patch anchor mismatch: {old[:80]!r}")
    return source.replace(old, new, 1)


def main(path: str) -> None:
    target = Path(path)
    source = target.read_text()
    digest = hashlib.sha256(source.encode()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise RuntimeError(f"Hermes api_server.py digest mismatch: {digest}")
    start = source.index('    async def _handle_runs(self, request: "web.Request")')
    end = source.index('    async def _handle_get_run(self, request: "web.Request")', start)
    prefix, handler, suffix = source[:start], source[start:end], source[end:]
    handler = replace_once(
        handler,
        '''        raw_input = body.get("input")\n''',
        '''        from gateway.platform_capabilities import PlatformCapabilityError, pop_platform_context\n        try:\n            platform_context = pop_platform_context(body)\n        except PlatformCapabilityError as exc:\n            return web.json_response(_openai_error(str(exc)), status=400)\n\n        raw_input = body.get("input")\n''',
    )
    handler = replace_once(
        handler,
        '''        run_id = f"run_{uuid.uuid4().hex}"\n        session_id = session_id or run_id\n''',
        '''        run_id = f"run_{uuid.uuid4().hex}"\n        session_id = session_id or run_id\n        from gateway.platform_capabilities import register_run\n        try:\n            register_run(run_id, session_id, platform_context)\n        except PlatformCapabilityError as exc:\n            return web.json_response(_openai_error(str(exc)), status=400)\n''',
    )
    handler = replace_once(
        handler,
        '''                self._active_run_agents[run_id] = agent\n''',
        '''                from gateway.platform_capabilities import attach_run_tools\n                attach_run_tools(agent, run_id)\n                self._active_run_agents[run_id] = agent\n''',
    )
    handler = replace_once(
        handler,
        '''                self._active_run_agents.pop(run_id, None)\n''',
        '''                from gateway.platform_capabilities import unregister_run\n                unregister_run(run_id)\n                self._active_run_agents.pop(run_id, None)\n''',
    )
    target.write_text(prefix + handler + suffix)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_api_server.py <api_server.py>")
    main(sys.argv[1])
