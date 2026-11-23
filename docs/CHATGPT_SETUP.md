# ChatGPT Setup — connect ChatGPT (or any OpenAI-protocol client) to AgentHive

ChatGPT cannot run MCP STDIO. AgentHive therefore exposes an
**OpenAI-compatible server** — ChatGPT-flavoured clients talk to AgentHive
with the ordinary `/v1/chat/completions` protocol, and a **custom GPT /
GPT Action** can drive the 18 tools over REST.

> Claim discipline: the wire behaviour below is verified by automated tests
> (`tests/test_connectors_api.py`); the custom-GPT UI steps are the standard
> OpenAI Action configuration and were not hand-executed inside ChatGPT by
> the maintainers.

## 1. OpenAI-compatible endpoint (chat)

```
GET  /v1/models              → agent personas as models
POST /v1/chat/completions    → the hive answers (mission execution)
POST /v1/responses           → session continuity (resume by session id)
```

```bash
curl -s http://localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer $AGENT_HIVE_TOKEN" \
  -d '{"model":"agent-hive/master",
       "messages":[{"role":"user","content":"Plan a sprint for the payments team"}],
       "session_id":"chatgpt-session-1"}'
```

The assistant message contains the mission deliverable. `stream: true`
returns standard SSE `chat.completion.chunk` frames terminated by
`data: [DONE]`.

**Tool invocation without MCP**: put an explicit invocation as the user
message and the connector executes it and returns the structured result:

```json
{"name": "agent_save_memory",
 "arguments": {"memory_type": "task", "key": "sprint-42",
               "content": "sprint 42 scope agreed", "session_id": "chatgpt-session-1"}}
```

or the compact form `@agent_save_memory {"key": "...", "memory_type": "task", ...}`.

The response also carries an `agent_hive.tool_result` extension field with
the structured payload.

**Session continuity** (cross-client): `POST /v1/responses` with
`{"session_id": "chatgpt-session-1", "instruction": "continue"}` loads the
context stored by *any* client into the conversation.

## 2. Custom GPT / GPT Action (REST)

1. Publish AgentHive over HTTPS (reverse proxy + TLS; never expose raw HTTP).
2. Issue a token: `agent-hive token --role operator` (or
   `POST /api/security/tokens` from an admin).
3. In the GPT builder → Actions → import this OpenAPI snippet:

```yaml
openapi: 3.1.0
info: {title: AgentHive, version: "1.0"}
servers: [{url: "https://your-host"}]
paths:
  /api/universal/request:
    post:
      operationId: universalRequest
      summary: Run a mission and get the deliverable
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [instruction]
              properties:
                instruction: {type: string}
                session_id: {type: string}
                client_id: {type: string}
      responses:
        "200": {description: mission result}
  /api/universal/tool:
    post:
      operationId: universalTool
      summary: Execute one of the 18 AgentHive tools by name
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              required: [name]
              properties:
                name: {type: string}
                arguments: {type: object}
      responses:
        "200": {description: tool result}
  /api/universal/memory:
    get:
      operationId: searchMemory
      summary: Search the cross-client shared memory
      parameters:
        - {name: q, in: query, schema: {type: string}}
        - {name: session_id, in: query, schema: {type: string}}
      responses:
        "200": {description: matching records}
components:
  securitySchemes:
    bearer: {type: http, scheme: bearer}
security: [{bearer: []}]
```

4. Tool manifest for function-calling UIs: `GET /api/universal/tools`
   (OpenAI-style `{name, description, parameters}` list — usable by any
   function-calling client: LangChain, Dify, n8n, LibreChat…).

## 3. ChatGPT as AgentHive's model provider

ChatGPT itself is reached through the `openai` preset (OpenAI-compatible):

```yaml
providers:
  - type: openai_compatible
    model: gpt-4o-mini
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
```
