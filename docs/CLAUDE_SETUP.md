# Claude Setup — Claude Desktop, Claude Code and the Claude API

Three ways Claude can work with AgentHive:

## 1. Claude Desktop as an MCP client (recommended)

AgentHive ships a real MCP server (Streamable HTTP + STDIO). Full details and
verification steps: [`MCP_SETUP.md`](MCP_SETUP.md).

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "agent-hive": { "command": "agent-hive", "args": ["mcp"] }
  }
}
```

The MCP session runs with local trust (full scopes). Typical Claude flow:

1. `agent_get_capabilities` — discover the 18 tools;
2. `agent_execute` — Claude describes the goal in natural language; the
   Master Agent plans, delegates to specialist agents, verifies quality and
   returns the deliverable;
3. `agent_save_memory` — Claude stores decisions/results in the **universal
   shared memory** so other clients (ChatGPT, Gemini, Z.ai) can pick up the
   work later;
4. `agent_search_memory` — Claude retrieves what another client stored.

## 2. Claude API as AgentHive's *model* provider

The `anthropic_native` provider is a real adapter for the Anthropic Messages
API (it is **not** OpenAI-compatible wire-wise, which is why a dedicated
adapter exists):

* endpoint `POST {base_url}/v1/messages`;
* `x-api-key` + `anthropic-version: 2023-06-01` headers;
* system prompt as top-level `system` field; `max_tokens` required;
* response text at `content[0].text`.

`configs/agents/<agent>.yaml` provider stanza (or use the preset):

```yaml
providers:
  - type: anthropic_native
    model: claude-sonnet-4-5
    base_url: https://api.anthropic.com
    api_key_env: ANTHROPIC_API_KEY
```

`.env`: `ANTHROPIC_API_KEY=sk-ant-...`. Without a key the chain falls back
(per config order) to Ollama/mock — the mock is always tagged `[MOCK]`.

## 3. Claude accessing AgentHive remotely over MCP-HTTP

For Claude deployments that support remote MCP connectors, point them at:

```
http://<host>:8000/mcp        # Authorization: Bearer <token>
```

Initialize → tools/list (18 tools) → tools/call, as shown in
[`MCP_SETUP.md`](MCP_SETUP.md).

## What is verified vs. assumed

* **VERIFIED** (automated tests): MCP protocol behaviour on both transports,
  the 18-tool surface, cross-client memory, scope enforcement, the Anthropic
  adapter wire format (contract-level, against a mock transport).
* **UNTESTED-BY-US** (documented, vendor-defined): the exact `claude_desktop_config.json`
  UX inside the Claude Desktop app and live API behaviour with a real key.
