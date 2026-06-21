# Architecture Decision Records (ADR)

All architecture decisions for this project live in this single file. Older numbers stay stable when you add new sections at the bottom.

| ID | Title | Phase |
|----|--------|-------|
| [0001](#adr-0001) | Model stack: keep Claude Agent SDK + CLI transport | Phase 0 |
| [0002](#adr-0002) | Model config: `AGENT_MODEL` env var | Phase 0 |
| [0003](#adr-0003) | Observability: startup self-check logs (stderr) | Phase 0 |
| [0004](#adr-0004) | Benchmark URL set: `data/benchmarks.json` | Phase 0 |

---

<a id="adr-0001"></a>

## 0001 — Model stack: keep Claude Agent SDK + CLI transport

- **Status**: Accepted
- **Date**: 2026-06-19
- **Phase**: Phase 0

### Context

The starter uses `ClaudeSDKClient` from `claude-agent-sdk`. By default it uses `SubprocessCLITransport` to run the Claude Code CLI on this machine (or the bundled `claude` from the SDK). It does **not** call the Anthropic HTTP API from Python. On a dev machine you may have no `ANTHROPIC_API_KEY`, but you are logged in through the CLI.

### Decision

**Keep Claude Agent SDK + CLI transport as the only model stack.** We do not add a bare API-key client or local Ollama as the default path.

### Rationale

- Matches the official starter. MCP tools (`write_html` / `read_html`), `WebFetch` / `WebSearch`, and the rest are already wired.
- CLI login is enough to run locally. Less setup friction.
- The README asks for an agentic flow and tool design, not a new LLM vendor under the hood.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Anthropic Python SDK, direct HTTP | No CLI needed | You must build the agent loop and tool protocol yourself; drifts from the starter | Not chosen |
| Local Ollama | Free, can work offline | Does not fit `claude-agent-sdk`; large effort | Not chosen |
| Claude Agent SDK + CLI | No rewrite, full tools | Needs CLI install and login; model names come from the CLI | **Chosen** |

### Consequences and risks

- **Impact**: `server.py` keeps `ClaudeSDKClient`. Auth issues mean checking the CLI, not only `.env`.
- **Risk**: CI or deploy has no CLI → Phase 7 needs docs or an image with the CLI pre-installed.

---

<a id="adr-0002"></a>

## 0002 — Model config: `AGENT_MODEL` env var

- **Status**: Accepted
- **Date**: 2026-06-19
- **Phase**: Phase 0

### Context

`ClaudeAgentOptions.model` used to be hard-coded (e.g. `haiku` / `opus`). That made it slow to try cost vs quality tradeoffs. The README example also did not pick one default model.

### Decision

Set the model alias with env var **`AGENT_MODEL`**. **Default is `opus`**. Support SDK aliases like `sonnet`, `haiku`, `inherit`. Put `AGENT_MODEL=opus` in `.env.example`.

```python
model=os.environ.get("AGENT_MODEL", "opus"),
```

### Rationale

- You can switch quality, speed, and cost for dev or demo without code edits.
- `load_dotenv()` already runs at startup in `server.py`, same pattern as `.env`.
- Default `opus` fits the README goal of a close visual copy.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Hard-code in code | Simple | Every switch needs a code edit; easy to commit by mistake | Not chosen |
| CLI flag `--model` | Very clear | Annoying with uvicorn reload and many processes | Not chosen |
| Env var `AGENT_MODEL` | Matches `.env`, easy to document | Must restart the server | **Chosen** |

### Consequences and risks

- **Impact**: `server.py` `_build_agent_options`; startup self-check logs the active model.
- **Risk**: Bad alias → error from CLI; startup log shows `AGENT_MODEL` to help debug.

---

<a id="adr-0003"></a>

## 0003 — Observability: startup self-check logs (stderr)

- **Status**: Accepted
- **Date**: 2026-06-19
- **Phase**: Phase 0

### Context

Developers were confused: “Why does the model work with no `.env`?” Auth actually comes from the Claude CLI. Without a clear print of runtime settings at boot, debugging cost time.

### Decision

In FastAPI `lifespan` startup, call **`_startup_selfcheck()`** and print to **stderr** (never print secrets):

- Current `AGENT_MODEL`
- **transport**: whether `claude` on PATH or the SDK bundled CLI exists
- **Whether `.env` exists** (boolean only; do not read or print key values)

Later phases keep using the existing SSE `_push_chat` for agent progress. This ADR does not extend that.

### Rationale

- Small change: only `server.py`, no new deps.
- stderr matches uvicorn logs; works locally and in containers.
- Makes clear: “CLI login” vs “API key in `.env`” are two different paths.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| `/health` returns config JSON | Can check from afar | May leak deploy details; too much design | Not chosen |
| Docs only | No code | Still invisible at runtime | Not chosen |
| stderr self-check in lifespan | Fast, no secret leak | Not structured JSON | **Chosen** |

### Consequences and risks

- **Impact**: Each server boot adds 3–4 log lines.
- **Risk**: If we add more transports later, we must extend the self-check output.

---

<a id="adr-0004"></a>

## 0004 — Benchmark URL set: `data/benchmarks.json`

- **Status**: Accepted
- **Date**: 2026-06-19
- **Phase**: Phase 0

### Context

Later phases (vision loop, similarity scores, regression) need a fixed set of target sites. We should not type a new URL every time; that makes results hard to compare.

### Decision

Keep **3–5** benchmark sites in **`data/benchmarks.json`**. Format: JSON array. Each item:

```json
{
  "id": "stripe",
  "url": "https://stripe.com",
  "note": "Complex SaaS landing page, many gradients and components"
}
```

Track the file in git (`data/` exists; only `data/.session_id` is gitignored).

### Rationale

- Same folder as `data/sessions.json`, fits project data layout.
- Humans can read it; scripts can `json.load`; Phase 5 batch runs can reuse it.
- Stable `id` helps reports and links into this file.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Hard-code in Python | No extra file | URL changes need code edits | Not chosen |
| YAML | Readable | Extra format / dep | Not chosen |
| `data/benchmarks.json` | Simple, matches `data/` | List is manual | **Chosen** |

### Consequences and risks

- **Impact**: Phase 1+ test scripts read this file; add sites by editing JSON.
- **Risk**: Remote sites change layout → drift. Use `note` for what matters; keep screenshot archives for evals.

---

## Adding a new ADR

Use the next free number (0005, 0006, …). Append a new section at the bottom of this file with the same shape:

- **Status**: Proposed | Accepted | Superseded by NNNN  
- **Date**: YYYY-MM-DD  
- **Phase**: Phase N  

Then subsections: **Context**, **Decision**, **Rationale**, **Alternatives** (table), **Consequences and risks**.

Add a row to the table at the top and an `<a id="adr-NNNN"></a>` anchor before the new `##` heading.

For the same phase, add or update the matching section in [`INTERVIEW.md`](INTERVIEW.md) and link ADR rows to `ADR.md#adr-NNNN`.
