# Gemini Setup — Google Gemini with AgentHive

Two directions, both real:

## 1. Gemini as AgentHive's model provider (native adapter)

Gemini's native API differs from OpenAI's wire format, so AgentHive ships a
dedicated `gemini_native` adapter (contract verified against a mock
transport; live behaviour needs your API key):

* endpoint `POST {base_url}/v1beta/models/{model}:generateContent`;
* API key in the `x-goog-api-key` header;
* system prompt → `systemInstruction.parts[0].text`;
* roles `user`/`model` (not `assistant`), content as `parts: [{text}]`;
* response text at `candidates[0].content.parts[*].text`.

`.env`:

```
GEMINI_API_KEY=AIza...
```

Agent YAML (or the `gemini` preset):

```yaml
providers:
  - type: gemini_native
    model: gemini-2.5-flash
    base_url: https://generativelanguage.googleapis.com
    api_key_env: GEMINI_API_KEY
```

**Fallback option** — Gemini also exposes an OpenAI-compatible mirror:

```yaml
providers:
  - type: openai_compatible
    model: gemini-2.5-flash
    base_url: https://generativelanguage.googleapis.com/v1beta/openai/
    api_key_env: GEMINI_API_KEY
```

Use the native adapter when you want Google-side feature parity; use the
mirror for uniformity with other OpenAI-compatible providers.

## 2. Gemini / AI Studio as an AgentHive *client*

Gemini applications (Gems, AI Studio apps, Vertex agents) consume AgentHive
through:

* **REST** — `POST /api/universal/request`, `POST /api/universal/tool`;
* **generic tool calling** — fetch `GET /api/universal/tools` and register
  the returned `{name, description, parameters}` entries as Gemini function
  declarations; when Gemini emits a function call, execute it server-side:

```python
import httpx

manifest = httpx.get("http://localhost:8000/api/universal/tools").json()["tools"]
# pass `manifest` as functionDeclarations to Gemini; on functionCall:
result = httpx.post(
    "http://localhost:8000/api/universal/tool",
    json={"name": call["name"], "arguments": call["args"]},
).json()
```

* **MCP over HTTP** — `POST /mcp` (Streamable HTTP), see
  [`MCP_SETUP.md`](MCP_SETUP.md).

Cross-client continuity: whatever Gemini stores via
`agent_save_memory`/missions is visible to Claude, ChatGPT, Z.ai and every
other connected client, namespaced by user/project/session and protected by
the access levels (`private|project|public`).
