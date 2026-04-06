#!/usr/bin/env python3
"""
Lightweight MCP approval server for claude -p permission requests.

Reads a JSON policy file that specifies:
- Allowed tools
- Allowed folders (with read/write permissions)

Usage:
  1. Create a policy file (e.g. approval-policy.json):
     {
       "tools": ["Read", "Write", "Edit", "Glob", "Grep"],
       "folders": {
         "/tmp/my-project": ["read", "write"],
         "/home/user/reference": ["read"]
       }
     }

  2. Add to mcp-servers.json:
     {
       "mcpServers": {
         "approval": {
           "command": "python3",
           "args": ["/path/to/approval_server.py", "/path/to/approval-policy.json"]
         }
       }
     }

  3. Run claude -p with:
     claude -p --mcp-config mcp-servers.json \\
       --permission-prompt-tool mcp__approval__permissions__approve \\
       "your prompt"
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

log = logging.getLogger("ntt.approval")

mcp = FastMCP("approval")

# Load policy from the file path passed as first CLI arg.
_policy_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
_policy: dict = {}

if _policy_path and _policy_path.exists():
    _policy = json.loads(_policy_path.read_text(encoding="utf-8"))
    log.info("Loaded policy from %s", _policy_path)
else:
    log.warning("No policy file found at %s — denying everything", _policy_path)

_allowed_tools: list[str] = _policy.get("tools", [])
_folders: dict[str, list[str]] = _policy.get("folders", {})


def _check_path(file_path: str, needs_write: bool) -> bool:
    """Check if a file path is allowed by the folder policy."""
    try:
        resolved = Path(file_path).resolve()
    except (ValueError, OSError):
        return False

    for folder, perms in _folders.items():
        folder_resolved = Path(folder).resolve()
        try:
            resolved.relative_to(folder_resolved)
        except ValueError:
            continue
        # Path is under this folder — check permissions.
        if needs_write and "write" not in perms:
            return False
        if not needs_write and "read" not in perms:
            return False
        return True

    return False


@mcp.tool()
async def permissions__approve(tool_name: str, input: dict, reason: str = "") -> dict:
    """Approve or deny permission requests based on policy file."""

    # Check if tool is allowed at all.
    if tool_name not in _allowed_tools:
        return {
            "behavior": "deny",
            "message": f"Tool '{tool_name}' not in allowed tools list",
        }

    # For file tools, check the path against folder policy.
    if tool_name in ("Read", "Glob", "Grep"):
        file_path = input.get("file_path") or input.get("path") or input.get("pattern", "")
        if not _check_path(file_path, needs_write=False):
            return {
                "behavior": "deny",
                "message": f"Read not allowed for path: {file_path}",
            }

    if tool_name in ("Write", "Edit"):
        file_path = input.get("file_path", "")
        if not _check_path(file_path, needs_write=True):
            return {
                "behavior": "deny",
                "message": f"Write not allowed for path: {file_path}",
            }

    if tool_name == "Bash":
        # Bash is allowed only if it's in the tools list.
        # No path checking — the tool list is the gate.
        pass

    return {
        "behavior": "allow",
        "updatedInput": input,
    }


if __name__ == "__main__":
    import asyncio
    asyncio.run(mcp.run())
