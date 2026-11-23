"""Package execution entry point: ``python -m agent_hive``.

Enables the STDIO MCP server workflow from clients that spawn the
process, e.g. Claude Desktop::

    "agent-hive": {"command": "agent-hive", "args": ["mcp"]}
"""

from agent_hive.cli import main

if __name__ == "__main__":
    main()
