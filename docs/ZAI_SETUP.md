# Z.ai Setup — GLM models and Z.ai chat with AgentHive

## 1. Z.ai GLM as AgentHive's model provider

Z.ai exposes an OpenAI-compatible API (`/api/paas/v4`). Preset `zai`:

```yaml
providers:
  - type: openai_compatible
    model: glm-4.6
    base_url: https://api.z.ai/api/paas/v4
    api_key_env: ZAI_API_KEY
```

`.env`: `ZAI_API_KEY=<your key>`. Without a key the provider reports
`configured=False` and the chain falls back (per config order) to the next
provider, ultimately the deterministic mock (tagged `[MOCK]`).

Chain example — GLM first, Ollama second, mock last:

```yaml
providers:
  - type: openai_compatible
    model: glm-4.6
    base_url: https://api.z.ai/api/paas/v4
    api_key_env: ZAI_API_KEY
  - type: ollama
    model: llama3.2
  - type: mock
```

## 2. The Z.ai chat (this assistant) working *on* the AgentHive repo

The Z.ai chat environment connects to GitHub through its GitHub integration
and to the local sandbox with a clone of the repository. Concretely:

* clone: `git clone https://github.com/rajuferr-sketch/agent-hive`;
* run the suite in the sandbox: `pytest tests/ -q` (224 tests) — no network
  or keys needed (`ALLOW_MOCK=true`);
* PR/branch operations go through the chat's GitHub plugin tools (the
  sandbox has no git push credentials of its own);
* AgentHive's own GitHub client (`docs/SECURITY.md` → GitHub modes) is the
  in-product equivalent for autonomous operation.

## 3. Z.ai GLM applications as AgentHive *clients*

Any GLM-based app can call:

* `POST /api/universal/request` — natural-language mission;
* `POST /api/universal/tool` — direct tool call, e.g.:

```bash
curl -s http://localhost:8000/api/universal/tool \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"name":"agent_search_memory","arguments":{"query":"sprint 42 scope","session_id":"zai-1"}}'
```

* OpenAI-compatible bridge — point a GLM client at `/v1/chat/completions`
  (see [`CHATGPT_SETUP.md`](CHATGPT_SETUP.md); same wire format).

Whatever Z.ai stores in the universal shared memory is immediately visible
to Claude Desktop, ChatGPT, Gemini and Ollama frontends on the same
user/project/session namespace.
