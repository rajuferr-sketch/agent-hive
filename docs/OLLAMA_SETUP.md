# Ollama Setup — local models and the Ollama-compatible connector

AgentHive integrates with Ollama in **both directions**, with no cloud
dependency.

## 1. Ollama as AgentHive's model provider (AgentHive → Ollama)

Standard Ollama provider (already in the default agent chains):

```yaml
providers:
  - type: ollama
    model: llama3.2
    # base_url optional; defaults to OLLAMA_BASE_URL or http://localhost:11434
```

```bash
export OLLAMA_BASE_URL=http://localhost:11434
ollama pull llama3.2
agent-hive run "Summarise the retention policy for customer records"
```

Provider behaviour (verified by tests):
* `POST /api/chat` with `stream:false`, `options` passthrough;
* usage counters (`prompt_eval_count`, `eval_count`) carried into results;
* `configured()` probes localhost once per 30 s so an absent Ollama does
  not spam connection errors; the chain falls through to mock (tagged).

Recommended local models: `llama3.2`, `qwen2.5`, `mistral`, `gemma2`,
`phi3` — anything Ollama serves works.

## 2. Ollama-compatible *server* (Ollama-aware UIs → AgentHive)

AgentHive speaks the Ollama protocol, so **Open WebUI, LibreChat, or any
Ollama client** can use the hive as if it were a local model:

```
GET  /api/tags       → agent personas listed as models (agent-hive:master, ...)
POST /api/chat       → {"message": {"role": "assistant", "content": ...}, "done": true}
POST /api/generate   → {"response": ..., "done": true}
```

Open WebUI example: Admin → Settings → Connections → add
`http://agenthive-host:8000` as an Ollama API endpoint. The
`agent-hive:master` pseudo-model routes prompts through the universal
gateway (mission execution), exactly like the REST/MCP paths.

Explicit tool invocation also works through the Ollama wire format — send
`{"name": "...", "arguments": {...}}` or `@tool_name {...}` as the message
content and the connector executes the tool.

## 3. Fully offline operation

```bash
ALLOW_MOCK=false            # no silent mock fallback
OLLAMA_BASE_URL=http://localhost:11434
```

With `ALLOW_MOCK=false` and no reachable provider the system returns a
clear `ProviderError` instead of pretending to work.

## Verification

```bash
curl -s http://localhost:8000/api/tags | python -m json.tool
curl -s http://localhost:8000/api/chat -d '{"model":"agent-hive:master",
  "messages":[{"role":"user","content":"one-line status"}]}' | python -m json.tool
```

Both endpoints are covered by the automated suite
(`tests/test_connectors_api.py`).
