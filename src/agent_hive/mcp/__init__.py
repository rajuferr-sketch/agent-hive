"""MCP (Model Context Protocol) server implementation.

Implements the MCP protocol without third-party SDK dependencies:

* JSON-RPC 2.0 message core (:mod:`agent_hive.mcp.server`);
* tool registry with the 18 platform tools (:mod:`agent_hive.mcp.tools`);
* Streamable HTTP transport mounted at ``/mcp`` (:mod:`agent_hive.mcp.http`);
* STDIO transport for local clients like Claude Desktop
  (:mod:`agent_hive.mcp.stdio`);
* a pragmatic JSON-Schema subset validator (:mod:`agent_hive.mcp.schema`).

Protocol surface: ``initialize``, ``notifications/initialized``, ``ping``,
``tools/list``, ``tools/call`` (``isError`` semantics respected).
"""

from agent_hive.mcp.schema import SchemaError, validate_schema

__all__ = ["SchemaError", "validate_schema"]
