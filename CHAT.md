# Using AgentHive inside an AI chat

0. Install dependencies once: `pip install -r requirements.txt`.
1. Download/clone the repository.
2. Run `python run.py --chat "your request"`.
3. AgentHive writes one JSON file per agent call into `./host_requests/`.
4. Read each request file, produce the answer, and write a JSON file with the same id into `./host_responses/`:
   ```json
   {"text": "<the agent's full answer>"}
   ```
5. AgentHive polls for responses and completes the mission, printing a Markdown report.

Files are consumed (deleted) after reading. You can answer them in any order.

See also: [`AGENTS.md`](AGENTS.md) — the full bootstrap protocol for AI agents working on this repository — and [`TASKS.md`](TASKS.md) — the current queue of assigned tasks.
